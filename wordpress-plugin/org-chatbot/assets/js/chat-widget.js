/**
 * Organization FAQ chatbot widget (SRS FR-21, FR-22; voice input per the proposed FR-24).
 *
 * - Built entirely here, so a blocked script or service never breaks the page (NFR-AVL-04).
 * - Keyboard and screen-reader friendly: real buttons, a labelled dialog, a polite live
 *   log, Esc to close and focus returned to the launcher (NFR-USE-01, WCAG 2.2 AA).
 * - Voice: asks for consent first, records up to `maxSeconds`, resamples to 16 kHz mono
 *   WAV in the browser and uploads it once. Nothing is stored in the browser.
 */
( function () {
	'use strict';

	const cfg = window.orgChatbotConfig;
	if ( ! cfg || ! cfg.serviceUrl ) {
		return;
	}
	const t = cfg.strings || {};
	const TARGET_RATE = 16000;
	const TEXT_TIMEOUT_MS = 12000;
	const VOICE_TIMEOUT_MS = 25000;
	const CONSENT_KEY = 'orgChatbotVoiceConsent';

	// Open the matching FAQ answer when a chatbot link points at #faq-123.
	function openFaqFromHash() {
		const match = /^#faq-\d+$/.exec( window.location.hash );
		const item = match && document.getElementById( match[ 0 ].slice( 1 ) );
		if ( item && item.tagName === 'DETAILS' ) {
			item.open = true;
		}
	}
	window.addEventListener( 'hashchange', openFaqFromHash );
	openFaqFromHash();

	/* ---------- helpers ---------- */

	function el( tag, attrs, children ) {
		const node = document.createElement( tag );
		Object.entries( attrs || {} ).forEach( ( [ key, value ] ) => {
			if ( value === false || value === null || value === undefined ) {
				return;
			}
			if ( key === 'text' ) {
				node.textContent = value;
			} else {
				node.setAttribute( key, value === true ? '' : String( value ) );
			}
		} );
		( children || [] ).forEach( ( child ) => child && node.append( child ) );
		return node;
	}

	function icon( path ) {
		const svg = document.createElementNS( 'http://www.w3.org/2000/svg', 'svg' );
		svg.setAttribute( 'viewBox', '0 0 24 24' );
		svg.setAttribute( 'aria-hidden', 'true' );
		svg.setAttribute( 'focusable', 'false' );
		const p = document.createElementNS( 'http://www.w3.org/2000/svg', 'path' );
		p.setAttribute( 'd', path );
		svg.append( p );
		return svg;
	}

	const ICONS = {
		chat: 'M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z',
		close: 'M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6L19 6.4 17.6 5 12 10.6z',
		send: 'M3 20.5 21 12 3 3.5V10l12 2-12 2z',
		mic: 'M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V21h2v-2.1a7 7 0 0 0 6-6.9z',
		stop: 'M7 7h10v10H7z',
	};

	const ALLOWED_TAGS = { P: [], BR: [], STRONG: [], B: [], EM: [], I: [], UL: [], OL: [], LI: [], A: [ 'href', 'title' ] };
	const DROP_TAGS = /^(SCRIPT|STYLE|IFRAME|OBJECT|EMBED|TEMPLATE|SVG|MATH)$/;

	// Allow-list sanitiser for answer HTML (the service and WordPress already clean it).
	function sanitize( html ) {
		const doc = new DOMParser().parseFromString( '<div>' + html + '</div>', 'text/html' );
		const root = doc.body.firstChild;
		( function walk( node ) {
			Array.from( node.childNodes ).forEach( ( child ) => {
				if ( child.nodeType === Node.TEXT_NODE ) {
					return;
				}
				if ( child.nodeType !== Node.ELEMENT_NODE || DROP_TAGS.test( child.tagName ) ) {
					child.remove();
					return;
				}
				if ( ! ( child.tagName in ALLOWED_TAGS ) ) {
					child.replaceWith( doc.createTextNode( child.textContent ) );
					return;
				}
				Array.from( child.attributes ).forEach( ( attr ) => {
					if ( ! ALLOWED_TAGS[ child.tagName ].includes( attr.name ) ) {
						child.removeAttribute( attr.name );
					}
				} );
				if ( child.tagName === 'A' ) {
					const href = child.getAttribute( 'href' ) || '';
					if ( ! /^(https?:|mailto:)/i.test( href ) ) {
						child.removeAttribute( 'href' );
					}
				}
				walk( child );
			} );
		} )( root );
		const fragment = document.createDocumentFragment();
		Array.from( root.childNodes ).forEach( ( n ) => fragment.append( document.importNode( n, true ) ) );
		return fragment;
	}

	async function request( path, options, timeoutMs ) {
		const controller = new AbortController();
		const timer = setTimeout( () => controller.abort(), timeoutMs );
		try {
			const response = await fetch( cfg.serviceUrl + path, { ...options, signal: controller.signal, credentials: 'omit' } );
			let body = null;
			try {
				body = await response.json();
			} catch ( e ) {
				body = null;
			}
			return { ok: response.ok, status: response.status, body };
		} finally {
			clearTimeout( timer );
		}
	}

	/* ---------- audio: capture, resample, WAV ---------- */

	function downsample( samples, inRate ) {
		if ( inRate === TARGET_RATE ) {
			return samples;
		}
		const ratio = inRate / TARGET_RATE;
		const out = new Float32Array( Math.floor( samples.length / ratio ) );
		for ( let i = 0; i < out.length; i++ ) {
			// Average each window: a simple low-pass that avoids aliasing.
			const start = Math.floor( i * ratio );
			const end = Math.min( samples.length, Math.floor( ( i + 1 ) * ratio ) );
			let sum = 0;
			for ( let j = start; j < end; j++ ) {
				sum += samples[ j ];
			}
			out[ i ] = sum / Math.max( 1, end - start );
		}
		return out;
	}

	function encodeWav( samples ) {
		const buffer = new ArrayBuffer( 44 + samples.length * 2 );
		const view = new DataView( buffer );
		const writeText = ( offset, text ) => {
			for ( let i = 0; i < text.length; i++ ) {
				view.setUint8( offset + i, text.charCodeAt( i ) );
			}
		};
		writeText( 0, 'RIFF' );
		view.setUint32( 4, 36 + samples.length * 2, true );
		writeText( 8, 'WAVE' );
		writeText( 12, 'fmt ' );
		view.setUint32( 16, 16, true ); // PCM chunk size
		view.setUint16( 20, 1, true ); // PCM
		view.setUint16( 22, 1, true ); // mono
		view.setUint32( 24, TARGET_RATE, true );
		view.setUint32( 28, TARGET_RATE * 2, true ); // byte rate
		view.setUint16( 32, 2, true ); // block align
		view.setUint16( 34, 16, true ); // bits per sample
		writeText( 36, 'data' );
		view.setUint32( 40, samples.length * 2, true );
		for ( let i = 0; i < samples.length; i++ ) {
			const s = Math.max( -1, Math.min( 1, samples[ i ] ) );
			view.setInt16( 44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true );
		}
		return new Blob( [ view ], { type: 'audio/wav' } );
	}

	class Recorder {
		async start( onAutoStop ) {
			this.chunks = [];
			this.stream = await navigator.mediaDevices.getUserMedia( {
				audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
			} );
			this.context = new AudioContext();
			await this.context.audioWorklet.addModule( cfg.workletUrl );
			this.source = this.context.createMediaStreamSource( this.stream );
			this.node = new AudioWorkletNode( this.context, 'org-chatbot-recorder' );
			this.node.port.onmessage = ( event ) => this.chunks.push( event.data );
			this.mute = this.context.createGain();
			this.mute.gain.value = 0; // keep the graph running without echoing the mic
			this.source.connect( this.node ).connect( this.mute ).connect( this.context.destination );
			this.timer = setTimeout( onAutoStop, ( cfg.maxSeconds || 15 ) * 1000 );
		}

		async stop() {
			clearTimeout( this.timer );
			const rate = this.context ? this.context.sampleRate : TARGET_RATE;
			if ( this.stream ) {
				this.stream.getTracks().forEach( ( track ) => track.stop() );
			}
			if ( this.context ) {
				await this.context.close();
			}
			const length = this.chunks.reduce( ( n, c ) => n + c.length, 0 );
			const merged = new Float32Array( length );
			let offset = 0;
			this.chunks.forEach( ( c ) => {
				merged.set( c, offset );
				offset += c.length;
			} );
			this.chunks = [];
			const samples = downsample( merged, rate );
			return { seconds: samples.length / TARGET_RATE, blob: encodeWav( samples ) };
		}
	}

	const voiceSupported =
		cfg.voiceEnabled &&
		window.isSecureContext &&
		!! ( navigator.mediaDevices && navigator.mediaDevices.getUserMedia ) &&
		typeof window.AudioWorkletNode === 'function';

	/* ---------- UI ---------- */

	// The visible name is the accessible name (WCAG 2.5.3 Label in Name); `title` adds the hint.
	const launcher = el( 'button', {
		type: 'button',
		class: 'org-chatbot__launcher',
		'aria-expanded': 'false',
		'aria-controls': 'org-chatbot-panel',
		title: t.open,
	}, [ icon( ICONS.chat ), el( 'span', { class: 'org-chatbot__launcher-label', text: cfg.botName } ) ] );

	const closeButton = el( 'button', { type: 'button', class: 'org-chatbot__icon-button', 'aria-label': t.close }, [ icon( ICONS.close ) ] );
	const log = el( 'div', { class: 'org-chatbot__log', role: 'log', 'aria-live': 'polite', tabindex: '0', 'aria-label': cfg.botName } );
	const input = el( 'input', { id: 'org-chatbot-input', type: 'text', maxlength: '300', autocomplete: 'off', placeholder: t.inputLabel } );
	const sendButton = el( 'button', { type: 'submit', class: 'org-chatbot__icon-button org-chatbot__send', 'aria-label': t.send }, [ icon( ICONS.send ) ] );
	const micButton = voiceSupported
		? el( 'button', { type: 'button', class: 'org-chatbot__icon-button org-chatbot__mic', 'aria-pressed': 'false', 'aria-label': t.mic }, [ icon( ICONS.mic ) ] )
		: null;
	const form = el( 'form', { class: 'org-chatbot__form' }, [
		el( 'label', { for: 'org-chatbot-input', class: 'org-chatbot__sr-only', text: t.inputLabel } ),
		input,
		micButton,
		sendButton,
	] );

	const consentAllow = el( 'button', { type: 'button', class: 'org-chatbot__button org-chatbot__button--primary', text: t.consentAllow } );
	const consentCancel = el( 'button', { type: 'button', class: 'org-chatbot__button', text: t.consentCancel } );
	const consent = el( 'div', { class: 'org-chatbot__consent', role: 'group', 'aria-labelledby': 'org-chatbot-consent-title', hidden: true }, [
		el( 'p', { id: 'org-chatbot-consent-title', class: 'org-chatbot__consent-title', text: t.consentTitle } ),
		el( 'p', { text: t.consentText } ),
		cfg.privacyUrl ? el( 'a', { href: cfg.privacyUrl, text: t.privacy } ) : null,
		el( 'div', { class: 'org-chatbot__consent-actions' }, [ consentAllow, consentCancel ] ),
	] );

	const panel = el( 'section', {
		id: 'org-chatbot-panel',
		class: 'org-chatbot__panel',
		role: 'dialog',
		'aria-modal': 'false',
		'aria-labelledby': 'org-chatbot-title',
		hidden: true,
	}, [
		el( 'header', { class: 'org-chatbot__header' }, [
			el( 'h2', { id: 'org-chatbot-title', class: 'org-chatbot__title', text: cfg.botName } ),
			closeButton,
		] ),
		log,
		consent,
		form,
		el( 'p', { class: 'org-chatbot__note' }, [
			document.createTextNode( t.note + ' ' ),
			cfg.privacyUrl ? el( 'a', { href: cfg.privacyUrl, text: t.privacy } ) : null,
		] ),
	] );

	const root = el( 'div', { class: 'org-chatbot' }, [ panel, launcher ] );

	function scrollToEnd() {
		log.scrollTop = log.scrollHeight;
	}

	function addMessage( who, content ) {
		const bubble = el( 'div', { class: 'org-chatbot__msg org-chatbot__msg--' + who } );
		if ( typeof content === 'string' ) {
			bubble.textContent = content;
		} else {
			bubble.append( content );
		}
		log.append( bubble );
		scrollToEnd();
		return bubble;
	}

	function linkList( links, label ) {
		if ( ! links || ! links.length ) {
			return null;
		}
		const list = el( 'ul', { class: 'org-chatbot__links' } );
		links.forEach( ( link ) => list.append( el( 'li', {}, [ el( 'a', { href: link.url, text: link.label } ) ] ) ) );
		return label ? el( 'div', {}, [ el( 'p', { class: 'org-chatbot__links-label', text: label } ), list ] ) : list;
	}

	function renderReply( reply ) {
		const body = document.createDocumentFragment();
		if ( reply.type === 'answer' && reply.html ) {
			body.append( sanitize( reply.html ) );
		} else {
			body.append( el( 'p', { text: reply.text } ) );
		}
		// Skip related links the answer already contains.
		const shown = new Set( Array.from( body.querySelectorAll( 'a[href]' ), ( a ) => a.getAttribute( 'href' ) ) );
		const links = ( reply.links || [] ).filter( ( link ) => ! shown.has( link.url ) );
		if ( reply.email && /^mailto:/i.test( reply.email.href ) ) {
			body.append( el( 'p', {}, [ el( 'a', { href: reply.email.href, class: 'org-chatbot__email', text: reply.email.label + ': ' + reply.email.address } ) ] ) );
		}
		body.append( linkList( links ) || document.createTextNode( '' ) );
		body.append( linkList( reply.suggestions, t.related ) || document.createTextNode( '' ) );
		return body;
	}

	// Shown when the service is unreachable: contact details come from WordPress, not the service.
	function offlineMessage() {
		const body = document.createDocumentFragment();
		body.append( el( 'p', { text: t.offline } ) );
		const contact = [];
		if ( cfg.contactUrl ) {
			contact.push( el( 'a', { href: cfg.contactUrl, text: t.contactPage } ) );
		}
		if ( cfg.generalEmail ) {
			contact.push( el( 'a', { href: 'mailto:' + cfg.generalEmail, text: cfg.generalEmail } ) );
		}
		if ( contact.length ) {
			const parts = [ document.createTextNode( t.offlineContact + ': ' ), contact[ 0 ] ];
			if ( contact[ 1 ] ) {
				parts.push( document.createTextNode( ' ' + t.offlineEmail + ' ' ), contact[ 1 ] );
			}
			body.append( el( 'p', {}, parts ) );
		}
		return body;
	}

	function setBusy( busy ) {
		input.disabled = busy;
		sendButton.disabled = busy;
		if ( micButton && ! recording ) {
			micButton.disabled = busy;
		}
	}

	async function handleResponse( pending, result ) {
		if ( result.ok && result.body ) {
			pending.replaceChildren( renderReply( result.body ) );
		} else if ( result.body && result.body.message && result.status < 500 ) {
			pending.textContent = result.body.message;
		} else {
			pending.replaceChildren( offlineMessage() );
		}
		pending.classList.remove( 'is-pending' );
		scrollToEnd();
	}

	async function ask( question ) {
		addMessage( 'user', question );
		const pending = addMessage( 'bot', t.thinking );
		pending.classList.add( 'is-pending' );
		setBusy( true );
		try {
			const result = await request(
				'/v1/chat',
				{ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify( { message: question } ) },
				TEXT_TIMEOUT_MS
			);
			await handleResponse( pending, result );
		} catch ( e ) {
			pending.replaceChildren( offlineMessage() );
			pending.classList.remove( 'is-pending' );
		} finally {
			setBusy( false );
			input.focus();
		}
	}

	/* ---------- voice flow ---------- */

	let recording = false;
	let recorder = null;
	let listeningNote = null;

	function hasConsent() {
		try {
			return window.sessionStorage.getItem( CONSENT_KEY ) === '1';
		} catch ( e ) {
			return false;
		}
	}

	function rememberConsent() {
		try {
			window.sessionStorage.setItem( CONSENT_KEY, '1' );
		} catch ( e ) {
			// Storage blocked: consent is asked again next time.
		}
	}

	function setRecordingUi( on ) {
		recording = on;
		micButton.setAttribute( 'aria-pressed', on ? 'true' : 'false' );
		micButton.setAttribute( 'aria-label', on ? t.stop : t.mic );
		micButton.replaceChildren( icon( on ? ICONS.stop : ICONS.mic ) );
		root.classList.toggle( 'is-recording', on );
	}

	async function startRecording() {
		recorder = new Recorder();
		try {
			await recorder.start( () => recording && stopRecording() );
			setRecordingUi( true );
			listeningNote = addMessage( 'note', t.listening );
		} catch ( e ) {
			recorder = null;
			addMessage( 'bot', t.micBlocked );
		}
	}

	async function stopRecording() {
		if ( ! recorder ) {
			return;
		}
		const active = recorder;
		recorder = null;
		setRecordingUi( false );
		if ( listeningNote ) {
			listeningNote.remove();
			listeningNote = null;
		}
		const { seconds, blob } = await active.stop();
		if ( seconds < 0.4 ) {
			addMessage( 'bot', t.tooShort );
			return;
		}
		const pending = addMessage( 'bot', t.transcribing );
		pending.classList.add( 'is-pending' );
		setBusy( true );
		try {
			const data = new FormData();
			data.append( 'audio', blob, 'question.wav' );
			const result = await request( '/v1/chat/voice', { method: 'POST', body: data }, VOICE_TIMEOUT_MS );
			if ( result.ok && result.body && result.body.transcript ) {
				log.insertBefore( el( 'div', { class: 'org-chatbot__msg org-chatbot__msg--user' }, [
					el( 'span', { class: 'org-chatbot__said', text: t.youSaid + ' ' } ),
					document.createTextNode( result.body.transcript ),
				] ), pending );
			}
			await handleResponse( pending, result );
		} catch ( e ) {
			pending.replaceChildren( offlineMessage() );
			pending.classList.remove( 'is-pending' );
		} finally {
			setBusy( false );
			micButton.focus();
		}
	}

	if ( micButton ) {
		micButton.addEventListener( 'click', () => {
			if ( recording ) {
				stopRecording();
			} else if ( hasConsent() ) {
				startRecording();
			} else {
				consent.hidden = false;
				consentAllow.focus();
			}
		} );
		consentAllow.addEventListener( 'click', () => {
			rememberConsent();
			consent.hidden = true;
			startRecording();
		} );
		consentCancel.addEventListener( 'click', () => {
			consent.hidden = true;
			micButton.focus();
		} );
	}

	/* ---------- open, close, submit ---------- */

	let greeted = false;

	function openPanel() {
		panel.hidden = false;
		launcher.setAttribute( 'aria-expanded', 'true' );
		root.classList.add( 'is-open' );
		if ( ! greeted && cfg.greeting ) {
			addMessage( 'bot', cfg.greeting );
			greeted = true;
		}
		input.focus();
	}

	function closePanel() {
		if ( recording ) {
			stopRecording();
		}
		panel.hidden = true;
		consent.hidden = true;
		launcher.setAttribute( 'aria-expanded', 'false' );
		root.classList.remove( 'is-open' );
		launcher.focus();
	}

	launcher.addEventListener( 'click', () => ( panel.hidden ? openPanel() : closePanel() ) );
	closeButton.addEventListener( 'click', closePanel );
	panel.addEventListener( 'keydown', ( event ) => {
		if ( event.key === 'Escape' ) {
			event.preventDefault();
			closePanel();
		}
	} );
	form.addEventListener( 'submit', ( event ) => {
		event.preventDefault();
		const question = input.value.trim();
		if ( question ) {
			input.value = '';
			ask( question );
		}
	} );

	function mount() {
		document.body.append( root );
	}
	if ( document.readyState === 'loading' ) {
		document.addEventListener( 'DOMContentLoaded', mount );
	} else {
		mount();
	}
} )();
