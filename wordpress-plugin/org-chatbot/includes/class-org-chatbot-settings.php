<?php
/**
 * Plugin settings: service connection, messages and inquiry concerns.
 *
 * @package OrgChatbot
 */

defined( 'ABSPATH' ) || exit;

/**
 * Stores and sanitises the plugin's settings in one option.
 */
class Org_Chatbot_Settings {

	const OPTION = 'org_chatbot_settings';
	const GROUP  = 'org_chatbot';

	/**
	 * Register the setting with its sanitiser.
	 */
	public static function init() {
		add_action( 'admin_init', array( __CLASS__, 'register' ) );
	}

	/**
	 * Register the option with the Settings API.
	 */
	public static function register() {
		register_setting(
			self::GROUP,
			self::OPTION,
			array(
				'type'              => 'array',
				'sanitize_callback' => array( __CLASS__, 'sanitize' ),
				'default'           => self::defaults(),
			)
		);
	}

	/**
	 * Default settings. Concerns follow FR-16; their emails are set by the client (TBD-07).
	 *
	 * @return array
	 */
	public static function defaults() {
		return array(
			'widget_enabled'     => true,
			'voice_enabled'      => true,
			'service_url'        => '',
			'shared_secret'      => '',
			'bot_name'           => __( 'Ask us', 'org-chatbot' ),
			'faq_post_type'      => 'org_faq',
			'faq_taxonomy'       => 'org_faq_category',
			'register_faq_type'  => true,
			'faq_page_url'       => '',
			'contact_page_url'   => '',
			'privacy_page_url'   => '',
			'greeting_message'   => __( 'Hi! Ask me a question about the Organization, its events, or volunteering.', 'org-chatbot' ),
			'fallback_message'   => __( 'Sorry, I can only answer questions from our FAQ, and I couldn\'t find an answer to that one. Please email us and the right team will get back to you.', 'org-chatbot' ),
			'default_concern'    => 'general',
			'log_retention_days' => 90,
			'concerns'           => array(
				array(
					'key'      => 'general',
					'label'    => __( 'General inquiries', 'org-chatbot' ),
					'email'    => '',
					'keywords' => array(),
					'links'    => array(),
				),
				array(
					'key'      => 'events',
					'label'    => __( 'Events', 'org-chatbot' ),
					'email'    => '',
					'keywords' => array( 'event', 'seminar', 'workshop', 'webinar', 'venue', 'schedule', 'calendar', 'registration form', 'certificate' ),
					'links'    => array(),
				),
				array(
					'key'      => 'membership',
					'label'    => __( 'Membership and volunteering', 'org-chatbot' ),
					'email'    => '',
					'keywords' => array( 'member', 'membership', 'volunteer', 'join', 'recruitment' ),
					'links'    => array(),
				),
				array(
					'key'      => 'partnerships',
					'label'    => __( 'Partnerships', 'org-chatbot' ),
					'email'    => '',
					'keywords' => array( 'partner', 'partnership', 'sponsor', 'sponsorship', 'collaborate' ),
					'links'    => array(),
				),
				array(
					'key'      => 'media',
					'label'    => __( 'Media', 'org-chatbot' ),
					'email'    => '',
					'keywords' => array( 'media', 'press', 'journalist', 'interview' ),
					'links'    => array(),
				),
			),
		);
	}

	/**
	 * All settings merged over the defaults.
	 *
	 * @return array
	 */
	public static function all() {
		$saved = get_option( self::OPTION, array() );
		return wp_parse_args( is_array( $saved ) ? $saved : array(), self::defaults() );
	}

	/**
	 * One setting.
	 *
	 * @param string $key Setting name.
	 * @return mixed
	 */
	public static function get( $key ) {
		$all = self::all();
		return $all[ $key ] ?? null;
	}

	/**
	 * Shared secret: the ORG_CHATBOT_SHARED_SECRET constant in wp-config.php wins over the stored value.
	 *
	 * @return string
	 */
	public static function secret() {
		if ( defined( 'ORG_CHATBOT_SHARED_SECRET' ) && '' !== (string) ORG_CHATBOT_SHARED_SECRET ) {
			return (string) ORG_CHATBOT_SHARED_SECRET;
		}
		return (string) self::get( 'shared_secret' );
	}

	/**
	 * Privacy Notice URL: the setting, else the site's privacy policy page.
	 *
	 * @return string
	 */
	public static function privacy_url() {
		$url = (string) self::get( 'privacy_page_url' );
		return '' !== $url ? $url : (string) get_privacy_policy_url();
	}

	/**
	 * Parse "Label | https://url" lines into link arrays.
	 *
	 * @param string $text One link per line.
	 * @return array
	 */
	public static function parse_links( $text ) {
		$links = array();
		foreach ( preg_split( '/\r\n|\r|\n/', (string) $text ) as $line ) {
			$parts = array_map( 'trim', explode( '|', $line, 2 ) );
			if ( 2 !== count( $parts ) ) {
				continue;
			}
			$url = esc_url_raw( $parts[1], array( 'http', 'https' ) );
			if ( '' !== $parts[0] && '' !== $url ) {
				$links[] = array(
					'label' => sanitize_text_field( $parts[0] ),
					'url'   => $url,
				);
			}
		}
		return $links;
	}

	/**
	 * Render link arrays back to "Label | URL" lines.
	 *
	 * @param array $links Links.
	 * @return string
	 */
	public static function format_links( $links ) {
		$lines = array();
		foreach ( (array) $links as $link ) {
			if ( is_array( $link ) && isset( $link['label'], $link['url'] ) ) {
				$lines[] = $link['label'] . ' | ' . $link['url'];
			}
		}
		return implode( "\n", $lines );
	}

	/**
	 * Report a validation problem on the settings screen (no-op outside wp-admin).
	 *
	 * @param string $code    Error code.
	 * @param string $message Message.
	 */
	private static function error( $code, $message ) {
		if ( function_exists( 'add_settings_error' ) ) {
			add_settings_error( self::OPTION, $code, $message );
		}
	}

	/**
	 * Sanitise the submitted settings.
	 *
	 * Must be idempotent: WordPress runs it twice on the first save (update_option
	 * then add_option), the second time on already-clean data, and it also runs
	 * when code calls update_option outside wp-admin.
	 *
	 * @param mixed $input Raw form input or an already-sanitised settings array.
	 * @return array
	 */
	public static function sanitize( $input ) {
		$input    = is_array( $input ) ? $input : array();
		$defaults = self::defaults();
		$clean    = array();

		$clean['widget_enabled']    = ! empty( $input['widget_enabled'] );
		$clean['voice_enabled']     = ! empty( $input['voice_enabled'] );
		$clean['register_faq_type'] = ! empty( $input['register_faq_type'] );

		$clean['service_url'] = untrailingslashit( esc_url_raw( (string) ( $input['service_url'] ?? '' ), array( 'https', 'http' ) ) );
		if ( '' !== $clean['service_url'] && 0 !== strpos( $clean['service_url'], 'https://' ) && ! self::is_local_url( $clean['service_url'] ) ) {
			self::error( 'service_url', __( 'The chatbot service URL must use https:// (plain http is only allowed for localhost).', 'org-chatbot' ) );
			$clean['service_url'] = '';
		}

		$secret                 = trim( (string) ( $input['shared_secret'] ?? '' ) );
		$clean['shared_secret'] = '' !== $secret ? sanitize_text_field( $secret ) : (string) self::get( 'shared_secret' );

		foreach ( array( 'faq_page_url', 'contact_page_url', 'privacy_page_url' ) as $key ) {
			$clean[ $key ] = esc_url_raw( (string) ( $input[ $key ] ?? '' ), array( 'http', 'https' ) );
		}
		foreach ( array( 'faq_post_type', 'faq_taxonomy' ) as $key ) {
			$value         = sanitize_key( (string) ( $input[ $key ] ?? '' ) );
			$clean[ $key ] = '' !== $value ? $value : $defaults[ $key ];
		}
		foreach ( array( 'bot_name', 'greeting_message', 'fallback_message' ) as $key ) {
			$value         = sanitize_textarea_field( (string) ( $input[ $key ] ?? '' ) );
			$clean[ $key ] = '' !== $value ? $value : $defaults[ $key ];
		}
		$clean['log_retention_days'] = max( 1, min( 365, absint( $input['log_retention_days'] ?? 90 ) ) );

		$clean['concerns'] = array();
		foreach ( (array) ( $input['concerns'] ?? array() ) as $row ) {
			$key   = sanitize_key( (string) ( $row['key'] ?? '' ) );
			$email = sanitize_email( (string) ( $row['email'] ?? '' ) );
			if ( '' === $key ) {
				continue;
			}
			if ( '' !== (string) ( $row['email'] ?? '' ) && ! is_email( $email ) ) {
				/* translators: %s: concern key. */
				self::error( 'email_' . $key, sprintf( __( 'The email for "%s" is not valid.', 'org-chatbot' ), $key ) );
				$email = '';
			}
			// Form input is text; already-saved values are arrays.
			$keywords_in = $row['keywords'] ?? '';
			$keywords_in = is_array( $keywords_in ) ? $keywords_in : explode( ',', (string) $keywords_in );
			$keywords    = array_filter( array_map( 'sanitize_text_field', array_map( 'trim', array_map( 'strval', $keywords_in ) ) ) );
			$links_in    = $row['links'] ?? '';
			$links_in    = is_array( $links_in ) ? self::format_links( $links_in ) : (string) $links_in;

			$clean['concerns'][] = array(
				'key'      => $key,
				'label'    => sanitize_text_field( (string) ( $row['label'] ?? $key ) ),
				'email'    => $email,
				'keywords' => array_values( $keywords ),
				'links'    => self::parse_links( $links_in ),
			);
		}
		$keys                     = wp_list_pluck( $clean['concerns'], 'key' );
		$default                  = sanitize_key( (string) ( $input['default_concern'] ?? 'general' ) );
		$clean['default_concern'] = in_array( $default, $keys, true ) ? $default : ( $keys[0] ?? 'general' );

		return $clean;
	}

	/**
	 * Whether a URL points at this machine (allowed over plain http for development).
	 *
	 * @param string $url URL.
	 * @return bool
	 */
	private static function is_local_url( $url ) {
		$host = (string) wp_parse_url( $url, PHP_URL_HOST );
		return in_array( $host, array( 'localhost', '127.0.0.1', '[::1]' ), true );
	}
}
