<?php
/**
 * REST endpoints used by the chatbot service (IF-11).
 *
 * GET  /wp-json/org-chatbot/v1/kb          the knowledge base
 * POST /wp-json/org-chatbot/v1/unanswered  record a question the bot could not answer
 *
 * Both require the X-Org-Chatbot-Key header to match the shared secret. Browsers
 * never call these; only the service does.
 *
 * @package OrgChatbot
 */

defined( 'ABSPATH' ) || exit;

/**
 * Service-facing REST routes.
 */
class Org_Chatbot_Rest {

	const NAMESPACE_V1 = 'org-chatbot/v1';

	/**
	 * Hook route registration.
	 */
	public static function init() {
		add_action( 'rest_api_init', array( __CLASS__, 'register_routes' ) );
	}

	/**
	 * Register the routes.
	 */
	public static function register_routes() {
		register_rest_route(
			self::NAMESPACE_V1,
			'/kb',
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => array( __CLASS__, 'get_kb' ),
				'permission_callback' => array( __CLASS__, 'check_key' ),
			)
		);
		register_rest_route(
			self::NAMESPACE_V1,
			'/unanswered',
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => array( __CLASS__, 'post_unanswered' ),
				'permission_callback' => array( __CLASS__, 'check_key' ),
				'args'                => array(
					'question' => array(
						'type'      => 'string',
						'required'  => true,
						'maxLength' => 300,
					),
					'source'   => array(
						'type'    => 'string',
						'enum'    => array( 'text', 'voice' ),
						'default' => 'text',
					),
				),
			)
		);
	}

	/**
	 * Allow the request only with the right shared secret.
	 *
	 * @param WP_REST_Request $request Request.
	 * @return true|WP_Error
	 */
	public static function check_key( $request ) {
		$secret = Org_Chatbot_Settings::secret();
		$key    = (string) $request->get_header( 'x_org_chatbot_key' );
		if ( '' !== $secret && '' !== $key && hash_equals( $secret, $key ) ) {
			return true;
		}
		return new WP_Error( 'org_chatbot_forbidden', __( 'Invalid chatbot key.', 'org-chatbot' ), array( 'status' => 403 ) );
	}

	/**
	 * Return the knowledge base.
	 *
	 * @return WP_REST_Response
	 */
	public static function get_kb() {
		$response = rest_ensure_response( Org_Chatbot_Knowledge_Base::payload() );
		$response->header( 'Cache-Control', 'no-store' );
		return $response;
	}

	/**
	 * Record an unanswered question.
	 *
	 * @param WP_REST_Request $request Request.
	 * @return WP_REST_Response
	 */
	public static function post_unanswered( $request ) {
		$saved = Org_Chatbot_Log::record( (string) $request['question'], (string) $request['source'] );
		return new WP_REST_Response( array( 'ok' => $saved ), $saved ? 201 : 200 );
	}
}
