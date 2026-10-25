<?php
/**
 * Front-end chat widget on every public page (FR-21).
 *
 * The widget is built entirely by a deferred script, so if the script or the
 * chatbot service is blocked the page itself is unaffected (NFR-AVL-04).
 *
 * @package OrgChatbot
 */

defined( 'ABSPATH' ) || exit;

/**
 * Enqueues the widget with its configuration.
 */
class Org_Chatbot_Widget {

	/**
	 * Hook asset loading.
	 */
	public static function init() {
		add_action( 'wp_enqueue_scripts', array( __CLASS__, 'enqueue' ) );
	}

	/**
	 * Email of the default concern, for the offline message.
	 *
	 * @param array $settings Settings.
	 * @return string
	 */
	private static function general_email( $settings ) {
		foreach ( (array) $settings['concerns'] as $concern ) {
			if ( $concern['key'] === $settings['default_concern'] ) {
				return (string) $concern['email'];
			}
		}
		return '';
	}

	/**
	 * Enqueue the widget script and styles.
	 */
	public static function enqueue() {
		$settings = Org_Chatbot_Settings::all();
		if ( empty( $settings['widget_enabled'] ) || '' === (string) $settings['service_url'] ) {
			return;
		}
		wp_enqueue_style( 'org-chatbot', ORG_CHATBOT_URL . 'assets/css/chat-widget.css', array(), ORG_CHATBOT_VERSION );
		wp_register_script(
			'org-chatbot',
			ORG_CHATBOT_URL . 'assets/js/chat-widget.js',
			array(),
			ORG_CHATBOT_VERSION,
			array(
				'in_footer' => true,
				'strategy'  => 'defer',
			)
		);
		$config = array(
			'serviceUrl'   => (string) $settings['service_url'],
			'voiceEnabled' => ! empty( $settings['voice_enabled'] ),
			'workletUrl'   => ORG_CHATBOT_URL . 'assets/js/recorder-worklet.js',
			'maxSeconds'   => 15,
			'botName'      => (string) $settings['bot_name'],
			'subtitle'     => get_bloginfo( 'name' ),
			'logoUrl'      => get_site_icon_url( 96 ),
			'greeting'     => (string) $settings['greeting_message'],
			'privacyUrl'   => Org_Chatbot_Settings::privacy_url(),
			'contactUrl'   => (string) $settings['contact_page_url'],
			'generalEmail' => self::general_email( $settings ),
			'strings'      => array(
				'open'             => __( 'Open the FAQ chatbot', 'org-chatbot' ),
				'close'            => __( 'Close chat', 'org-chatbot' ),
				'inputLabel'       => __( 'Type your question', 'org-chatbot' ),
				'send'             => __( 'Send question', 'org-chatbot' ),
				'mic'              => __( 'Ask by voice', 'org-chatbot' ),
				'stop'             => __( 'Stop recording and send', 'org-chatbot' ),
				'listening'        => __( 'Listening… press the microphone button again when you finish.', 'org-chatbot' ),
				'thinking'         => __( 'Looking that up…', 'org-chatbot' ),
				'transcribing'     => __( 'Turning your recording into text…', 'org-chatbot' ),
				'youSaid'          => __( 'You said:', 'org-chatbot' ),
				'related'          => __( 'Related questions', 'org-chatbot' ),				'note'             => __( 'Answers come only from our FAQ.', 'org-chatbot' ),
				'privacy'          => __( 'Privacy Notice', 'org-chatbot' ),
				'consentTitle'     => __( 'Ask by voice?', 'org-chatbot' ),
				'consentText'      => __( 'Your recording is sent to our chatbot service only to turn it into text so we can find the answer. The recording is not stored. Please do not say personal details such as your full name, phone number or ID numbers.', 'org-chatbot' ),
				'consentAllow'     => __( 'Allow and record', 'org-chatbot' ),
				'consentCancel'    => __( 'Cancel', 'org-chatbot' ),
				'micBlocked'       => __( 'The microphone is not available. Check your browser permission, or type your question instead.', 'org-chatbot' ),
				'tooShort'         => __( 'That recording was too short. Please try again.', 'org-chatbot' ),
				'offline'          => __( 'The chatbot is not available right now.', 'org-chatbot' ),
				'offlineContact'   => __( 'You can still reach us here', 'org-chatbot' ),
				'offlineEmail'     => __( 'or by email at', 'org-chatbot' ),
				'contactPage'      => __( 'Contact page', 'org-chatbot' ),
				'voiceUnsupported' => __( 'Voice questions are not supported in this browser.', 'org-chatbot' ),
			),
		);
		wp_add_inline_script( 'org-chatbot', 'window.orgChatbotConfig = ' . wp_json_encode( $config ) . ';', 'before' );
		wp_enqueue_script( 'org-chatbot' );
	}
}
