/**
 * Audio worklet that forwards raw microphone samples to the chat widget.
 * Runs on the audio rendering thread; the widget resamples to 16 kHz and
 * encodes WAV after recording stops.
 */
class OrgChatbotRecorder extends AudioWorkletProcessor {
	process( inputs ) {
		const channel = inputs[ 0 ] && inputs[ 0 ][ 0 ];
		if ( channel ) {
			this.port.postMessage( channel.slice( 0 ) );
		}
		return true;
	}
}

registerProcessor( 'org-chatbot-recorder', OrgChatbotRecorder );
