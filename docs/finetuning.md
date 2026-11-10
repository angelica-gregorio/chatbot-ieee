# Fine-tuning OWSM on our own recordings

The chatbot transcribes spoken questions with OWSM v3.1 base (`espnet/owsm_v3.1_ebf_base`, 101M parameters, E-Branchformer encoder). This page covers fine-tuning it on recordings of people asking the FAQ questions, then checking whether the fine-tuned model is actually better before switching the service to it.

## 1. Record the data

- Ask 15+ people (more people beats more clips per person) to ask the FAQ questions **in their own words**, through the chat widget's microphone or a laptop mic, in a normal room. Also include some out-of-scope questions ("what's the weather").
- Get each speaker's consent first. Recordings are personal data ([privacy.md](privacy.md)); `recordings/` and `*.wav` are git-ignored, so keep them there.
- Write each transcript **exactly as said, with normal casing and punctuation** (OWSM's own output style): `How do I join the organization?`. The model learns to output whatever you write.

## 2. Split by speaker into three CSVs

Same format as `eval/asr_eval.py`:

```
file,transcript,expected_faq_id,speaker
q01_ana.wav,How can I volunteer?,102,ana
q02_ana.wav,What's the weather tomorrow?,,ana
```

| File | Share of speakers | Used for |
| --- | --- | --- |
| `recordings/train.csv` | ~70% | training |
| `recordings/valid.csv` | ~15% | choosing the best epoch, early stopping |
| `recordings/test.csv` | ~15% | the final numbers; never used while training or tuning |

A speaker appears in **one file only**. `finetune_owsm.py` refuses to run if train and valid share a speaker. Clips from the same voice in train and test give numbers that look better than the model really is.

## 3. Set up a GPU environment (once)

The service's `.venv` has the CPU-only PyTorch. Make a separate environment with a CUDA build (the RTX 3050 laptop GPU, 4 GB, is enough with the default settings):

```bash
cd chatbot-service
py -3.13 -m venv .venv-train
.venv-train\Scripts\activate          # macOS/Linux: source .venv-train/bin/activate
# pick the CUDA index URL matching your driver at https://pytorch.org/get-started/locally/
pip install --index-url https://download.pytorch.org/whl/cu128 "torch==2.11.*" "torchaudio==2.11.*"
pip install -r requirements-ml.txt
python -c "import torch; print(torch.cuda.is_available())"   # must print True
```

No local GPU? The same commands work in Google Colab (GPU runtime). Upload the recordings to the Colab session only, not to a shared Drive.

## 4. Get the baseline first

Score the published model on the test speakers, with the old settings and the improved decoding:

```bash
python eval/asr_eval.py recordings/test.csv --sweep "1:0:1,3:0.3:1,3:0.3:3"
```

Each triple is `beam:ctc_weight:nbest`. The output gives WER, how many spoken questions got the right reply, and the latency for each setting. Write these down: they are the numbers fine-tuning has to beat.

## 5. Fine-tune

```bash
python scripts/finetune_owsm.py --train recordings/train.csv --valid recordings/valid.csv --out artifacts/owsm-ft
```

Defaults: 10 epochs, learning rate 1e-5, batch 2 with 4-step accumulation, the input layer and first 3 encoder blocks frozen, mixed precision, early stopping after 3 epochs without improvement. Each epoch prints train and validation loss. "Epoch 0" is the published weights, so you can see whether training helps at all.

Output in `artifacts/owsm-ft/` (git-ignored): `best.pth`, `last.pth` and `run.json` (settings, speakers, loss per epoch: the table for the report).

Things to try, one at a time, judged on **valid** loss and never on test:

| Change | Why |
| --- | --- |
| `--freeze-encoder-blocks 6` (all of them) | less data → train only the decoder; least overfitting |
| `--freeze-encoder-blocks 0` | more data → let the whole encoder adapt |
| `--lr 3e-5` or `5e-6` | the loss barely moves, or jumps around |
| `--epochs 20` | validation loss still falling at the last epoch |

If you run out of GPU memory, use `--batch-size 1 --accum 8` (same effective batch).

## 6. Compare on the test speakers

```bash
python eval/asr_eval.py recordings/test.csv --model-file artifacts/owsm-ft/best.pth --sweep "3:0.3:3"
```

Report it next to step 4: published OWSM with greedy decoding, published OWSM with better decoding, then fine-tuned OWSM. Watch **right reply** as well as WER: that's what visitors notice. Also check the out-of-scope rows still fall back. A model that "hears" FAQ questions everywhere is worse, not better.

## 7. Use it in the service

Only if step 6 shows the model is better:

```
ASR_MODEL_FILE=artifacts/owsm-ft/best.pth
ASR_BEAM_SIZE=3
ASR_CTC_WEIGHT=0.3
ASR_NBEST=3
```

`/health` then reports `"fine_tuned": true`. The config and tokenizer still come from `ASR_MODEL_TAG`, so keep that on the model you fine-tuned. Copy `best.pth` to the server yourself: it is 400 MB and is not in git.
