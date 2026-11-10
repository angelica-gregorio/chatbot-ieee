"""Fine-tune OWSM v3.1 (E-Branchformer) on your own recorded FAQ questions.

Input: two CSVs in the same format as eval/asr_eval.py, split BY SPEAKER
(nobody in the validation set may appear in the training set):

    file,transcript,expected_faq_id,speaker
    q01_ana.wav,How can I volunteer?,102,ana

Write transcripts the way OWSM writes them (normal casing and punctuation),
because the model learns to reproduce exactly what it is given.

Usage (needs a CUDA build of PyTorch; see docs/finetuning.md):

    python scripts/finetune_owsm.py --train recordings/train.csv --valid recordings/valid.csv \
        --out artifacts/owsm-ft --epochs 10

It writes ``best.pth`` (lowest validation loss), ``last.pth`` and ``run.json``
to ``--out``. Point the service at it with ``ASR_MODEL_FILE=.../best.pth``, and
score it on a third, held-out set of speakers with
``python eval/asr_eval.py recordings/test.csv --model-file .../best.pth``.

Audio goes through the same trimming and loudness normalisation as the service,
so the model is trained on what it will see. ESPnet's own OWSM preprocessor
builds the targets (``<eng><asr><notimestamps> text``) and the model's
SpecAugment is active while training.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.audio import decode_wav, prepare_for_asr  # noqa: E402


def load_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("transcript") or "").strip()]
    for row in rows:
        row["path"] = csv_path.parent / row["file"]
    return rows


def check_speakers(train: list[dict], valid: list[dict]) -> None:
    overlap = {r.get("speaker") for r in train} & {r.get("speaker") for r in valid}
    overlap.discard(None)
    overlap.discard("")
    if overlap:
        raise SystemExit(
            f"Speakers in both train and valid: {sorted(overlap)}. Split by speaker, or the "
            "validation loss will look better than the model really is."
        )


def build_examples(rows: list[dict], lang: str) -> list[tuple[str, dict]]:
    examples = []
    for i, row in enumerate(rows):
        audio = decode_wav(row["path"].read_bytes(), max_bytes=50_000_000, min_seconds=0.1, max_seconds=30)
        audio = prepare_for_asr(audio)
        text = row["transcript"].strip()
        examples.append(
            (
                f"utt{i:05d}",
                {
                    "speech": audio,
                    "text": f"{lang}<asr><notimestamps> {text}",
                    "text_prev": "<na>",
                    "text_ctc": text,
                },
            )
        )
    return examples


def batches(examples, preprocess, collate, batch_size: int, shuffle: bool):
    order = list(range(len(examples)))
    if shuffle:
        random.shuffle(order)
    for start in range(0, len(order), batch_size):
        chunk = [examples[i] for i in order[start : start + batch_size]]
        # The preprocessor copies what it changes, but give it fresh dicts anyway.
        yield collate([(uid, preprocess(uid, dict(data))) for uid, data in chunk])


def freeze_lower_encoder(model, blocks: int) -> int:
    """Freeze the input layer and the first ``blocks`` encoder blocks; return frozen parameter count."""
    frozen = 0
    encoder = model.encoder
    modules = [encoder.embed] if getattr(encoder, "embed", None) is not None else []
    modules += list(encoder.encoders)[:blocks]
    for module in modules:
        for param in module.parameters():
            param.requires_grad = False
            frozen += param.numel()
    return frozen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--valid", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "owsm-ft")
    parser.add_argument("--model-tag", default="espnet/owsm_v3.1_ebf_base")
    parser.add_argument("--lang", default="<eng>")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--lr", type=float, default=1e-5, help="small: the model already knows English")
    parser.add_argument("--warmup-steps", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=2, help="every clip is padded to 30 s")
    parser.add_argument("--accum", type=int, default=4, help="gradient accumulation steps")
    parser.add_argument("--freeze-encoder-blocks", type=int, default=3)
    parser.add_argument("--patience", type=int, default=3, help="stop after this many epochs without improvement")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--no-amp", action="store_true", help="train in float32 (slower, more memory)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    import torch
    from espnet2.tasks.s2t import S2TTask
    from espnet2.train.collate_fn import CommonCollateFn
    from espnet2.utils.pretrained import download_pretrained

    if args.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit(
            "CUDA is not available: this PyTorch is a CPU build or no GPU is visible. "
            "See docs/finetuning.md, or pass --device cpu (very slow)."
        )
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    train_rows, valid_rows = load_rows(args.train), load_rows(args.valid)
    check_speakers(train_rows, valid_rows)
    print(f"train {len(train_rows)} clips, valid {len(valid_rows)} clips")

    files = download_pretrained(args.model_tag)
    model, train_args = S2TTask.build_model_from_file(files["s2t_train_config"], files["s2t_model_file"], args.device)
    # Checkpoints are chosen on validation loss; WER is measured afterwards with
    # eval/asr_eval.py. Without this, validation also decodes for CER/WER (slow, needs editdistance).
    model.error_calculator = None
    encoder_class = type(model.encoder).__name__
    frozen = freeze_lower_encoder(model, args.freeze_encoder_blocks)
    total = sum(p.numel() for p in model.parameters())
    print(f"{args.model_tag}: {encoder_class}, {total / 1e6:.1f}M parameters, {frozen / 1e6:.1f}M frozen")

    preprocess_train = S2TTask.build_preprocess_fn(train_args, train=True)
    preprocess_valid = S2TTask.build_preprocess_fn(train_args, train=False)
    for pre in (preprocess_train, preprocess_valid):
        # Our targets already say <notimestamps>; never let the preprocessor insert a second one.
        pre.time_apply_prob = 1.0
    collate = CommonCollateFn(float_pad_value=0.0, int_pad_value=-1)

    train_examples = build_examples(train_rows, args.lang)
    valid_examples = build_examples(valid_rows, args.lang)

    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.01)
    steps_per_epoch = math.ceil(math.ceil(len(train_examples) / args.batch_size) / args.accum)
    total_steps = max(1, steps_per_epoch * args.epochs)

    def lr_at(step: int) -> float:  # linear warmup, then cosine decay to 10%
        if step < args.warmup_steps:
            return (step + 1) / args.warmup_steps
        progress = (step - args.warmup_steps) / max(1, total_steps - args.warmup_steps)
        return 0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, progress)))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_at)
    use_amp = args.device == "cuda" and not args.no_amp
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    def to_device(batch: dict) -> dict:
        return {k: v.to(args.device) if hasattr(v, "to") else v for k, v in batch.items()}

    def validate() -> float:
        model.eval()
        losses, weights = 0.0, 0
        with torch.no_grad():
            for _, batch in batches(valid_examples, preprocess_valid, collate, args.batch_size, shuffle=False):
                with torch.autocast("cuda", dtype=torch.float16, enabled=use_amp):
                    loss, _, weight = model(**to_device(batch))
                losses += float(loss) * int(weight)
                weights += int(weight)
        return losses / max(weights, 1)

    args.out.mkdir(parents=True, exist_ok=True)
    history = [{"epoch": 0, "valid_loss": round(validate(), 4)}]
    print(f"epoch 0 (published weights): valid loss {history[0]['valid_loss']:.4f}")
    best_loss, best_epoch, stale = history[0]["valid_loss"], 0, 0
    torch.save(model.state_dict(), args.out / "best.pth")

    for epoch in range(1, args.epochs + 1):
        model.train()
        started = time.perf_counter()
        running, count = 0.0, 0
        optimizer.zero_grad(set_to_none=True)
        for i, (_, batch) in enumerate(batches(train_examples, preprocess_train, collate, args.batch_size, True), 1):
            with torch.autocast("cuda", dtype=torch.float16, enabled=use_amp):
                loss, _, _ = model(**to_device(batch))
            scaler.scale(loss / args.accum).backward()
            running, count = running + loss.detach().item(), count + 1
            if i % args.accum == 0:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
        if count % args.accum:  # flush a partial accumulation at the end of the epoch
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)

        valid_loss = validate()
        record = {
            "epoch": epoch,
            "train_loss": round(running / max(count, 1), 4),
            "valid_loss": round(valid_loss, 4),
            "seconds": round(time.perf_counter() - started, 1),
        }
        history.append(record)
        print(json.dumps(record))
        torch.save(model.state_dict(), args.out / "last.pth")
        if valid_loss < best_loss:
            best_loss, best_epoch, stale = valid_loss, epoch, 0
            torch.save(model.state_dict(), args.out / "best.pth")
        else:
            stale += 1
            if stale >= args.patience:
                print(f"no improvement for {args.patience} epochs; stopping")
                break

    run = {
        "model_tag": args.model_tag,
        "encoder": encoder_class,
        "best_epoch": best_epoch,
        "best_valid_loss": best_loss,
        "train_clips": len(train_examples),
        "valid_clips": len(valid_examples),
        "train_speakers": sorted({r.get("speaker") or "" for r in train_rows}),
        "valid_speakers": sorted({r.get("speaker") or "" for r in valid_rows}),
        "args": {k: str(v) for k, v in vars(args).items()},
        "history": history,
    }
    (args.out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    note = " (no epoch beat the published weights)" if best_epoch == 0 else ""
    print(f"best epoch {best_epoch}{note}, valid loss {best_loss:.4f}; weights in {args.out / 'best.pth'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
