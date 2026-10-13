<?php
/**
 * Builds the knowledge base the chatbot service reads (FR-17, FR-21, FR-23).
 *
 * The payload is cached in a transient and rebuilt whenever an FAQ entry,
 * FAQ category or the plugin settings change. On a change the service is
 * told to reload, so edited answers go live without redeploying (FR-23 AC1).
 *
 * @package OrgChatbot
 */

defined( 'ABSPATH' ) || exit;

/**
 * Knowledge base payload and change notifications.
 */
class Org_Chatbot_Knowledge_Base {

	const TRANSIENT = 'org_chatbot_kb';

	/**
	 * Whether a change happened during this request.
	 *
	 * @var bool
	 */
	private static $dirty = false;

	/**
	 * Hook change detection.
	 */
	public static function init() {
		$post_type = (string) Org_Chatbot_Settings::get( 'faq_post_type' );
		$taxonomy  = (string) Org_Chatbot_Settings::get( 'faq_taxonomy' );

		add_action( "save_post_{$post_type}", array( __CLASS__, 'mark_dirty' ) );
		add_action( 'trashed_post', array( __CLASS__, 'maybe_mark_dirty' ) );
		add_action( 'untrashed_post', array( __CLASS__, 'maybe_mark_dirty' ) );
		add_action( 'deleted_post', array( __CLASS__, 'maybe_mark_dirty' ) );
		add_action( "created_{$taxonomy}", array( __CLASS__, 'mark_dirty' ) );
		add_action( "edited_{$taxonomy}", array( __CLASS__, 'mark_dirty' ) );
		add_action( "delete_{$taxonomy}", array( __CLASS__, 'mark_dirty' ) );
		add_action( 'update_option_' . Org_Chatbot_Settings::OPTION, array( __CLASS__, 'mark_dirty' ) );
		add_action( 'shutdown', array( __CLASS__, 'notify_service' ) );
	}

	/**
	 * Flag the knowledge base as changed.
	 */
	public static function mark_dirty() {
		self::$dirty = true;
		delete_transient( self::TRANSIENT );
	}

	/**
	 * Flag a change if the post is an FAQ entry.
	 *
	 * @param int $post_id Post id.
	 */
	public static function maybe_mark_dirty( $post_id ) {
		if ( get_post_type( $post_id ) === Org_Chatbot_Settings::get( 'faq_post_type' ) ) {
			self::mark_dirty();
		}
	}

	/**
	 * At the end of a request that changed the FAQ, ask the service to reload (non-blocking).
	 */
	public static function notify_service() {
		$url    = (string) Org_Chatbot_Settings::get( 'service_url' );
		$secret = Org_Chatbot_Settings::secret();
		if ( ! self::$dirty || '' === $url || '' === $secret ) {
			return;
		}
		self::$dirty = false;
		wp_remote_post(
			$url . '/v1/kb/refresh',
			array(
				'blocking' => false,
				'timeout'  => 2,
				'headers'  => array( 'X-Org-Chatbot-Key' => $secret ),
			)
		);
	}

	/**
	 * HTML allowed in answers sent to the chatbot.
	 *
	 * @return array
	 */
	public static function allowed_html() {
		return array(
			'p'      => array(),
			'br'     => array(),
			'strong' => array(),
			'b'      => array(),
			'em'     => array(),
			'i'      => array(),
			'ul'     => array(),
			'ol'     => array(),
			'li'     => array(),
			'a'      => array(
				'href'  => true,
				'title' => true,
			),
		);
	}

	/**
	 * Clean answer HTML from block-editor content.
	 *
	 * @param WP_Post $post FAQ entry.
	 * @return string
	 */
	public static function answer_html( $post ) {
		$html = do_blocks( $post->post_content );
		$html = strip_shortcodes( $html );
		$html = preg_replace( '/<!--.*?-->/s', '', $html );
		$html = wp_kses( $html, self::allowed_html(), array( 'http', 'https', 'mailto' ) );
		$html = wpautop( trim( $html ) );
		return trim( preg_replace( '#<p>\s*</p>#', '', $html ) );
	}

	/**
	 * Lines of a textarea meta field.
	 *
	 * @param int    $post_id Post id.
	 * @param string $key     Meta key.
	 * @return string[]
	 */
	private static function meta_lines( $post_id, $key ) {
		$lines = preg_split( '/\r\n|\r|\n/', (string) get_post_meta( $post_id, $key, true ) );
		return array_values( array_filter( array_map( 'trim', $lines ) ) );
	}

	/**
	 * The full knowledge base payload.
	 *
	 * @return array
	 */
	public static function payload() {
		$cached = get_transient( self::TRANSIENT );
		if ( is_array( $cached ) ) {
			return $cached;
		}

		$settings = Org_Chatbot_Settings::all();
		$taxonomy = (string) $settings['faq_taxonomy'];
		$faq_page = (string) $settings['faq_page_url'];
		$posts    = get_posts(
			array(
				'post_type'        => (string) $settings['faq_post_type'],
				'post_status'      => 'publish',
				'numberposts'      => -1,
				'orderby'          => array(
					'menu_order' => 'ASC',
					'title'      => 'ASC',
				),
				'suppress_filters' => false,
			)
		);

		$entries = array();
		foreach ( $posts as $post ) {
			if ( '0' === get_post_meta( $post->ID, Org_Chatbot_Faq::META_ENABLED, true ) ) {
				continue; // Disabled for the chatbot (FR-23).
			}
			$category = '';
			$concern  = '';
			$terms    = get_the_terms( $post, $taxonomy );
			if ( is_array( $terms ) && $terms ) {
				$category = $terms[0]->name;
				$concern  = (string) get_term_meta( $terms[0]->term_id, Org_Chatbot_Faq::TERM_CONCERN, true );
			}
			$html      = self::answer_html( $post );
			$entries[] = array(
				'id'            => (string) $post->ID,
				'question'      => wp_strip_all_tags( html_entity_decode( get_the_title( $post ), ENT_QUOTES, 'UTF-8' ) ),
				'alt_questions' => self::meta_lines( $post->ID, Org_Chatbot_Faq::META_ALT_QUESTIONS ),
				'answer_html'   => $html,
				'answer_text'   => trim( html_entity_decode( wp_strip_all_tags( $html ), ENT_QUOTES, 'UTF-8' ) ),
				'category'      => $category,
				'concern'       => $concern,
				'url'           => '' !== $faq_page ? $faq_page . '#faq-' . $post->ID : '',
				'links'         => Org_Chatbot_Settings::parse_links( (string) get_post_meta( $post->ID, Org_Chatbot_Faq::META_LINKS, true ) ),
			);
		}

		$concerns = array();
		foreach ( (array) $settings['concerns'] as $concern ) {
			if ( '' !== (string) $concern['email'] ) {
				$concerns[] = $concern;
			}
		}

		$body    = array(
			'fallback_message' => $settings['fallback_message'],
			'greeting_message' => $settings['greeting_message'],
			'contact_url'      => $settings['contact_page_url'],
			'default_concern'  => $settings['default_concern'],
			'concerns'         => $concerns,
			'entries'          => $entries,
		);
		$payload = array_merge(
			array(
				'version'      => substr( md5( (string) wp_json_encode( $body ) ), 0, 16 ),
				'generated_at' => gmdate( 'c' ),
			),
			$body
		);
		set_transient( self::TRANSIENT, $payload, HOUR_IN_SECONDS );
		return $payload;
	}
}
