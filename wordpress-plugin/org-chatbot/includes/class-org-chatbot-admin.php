<?php
/**
 * Admin screens: settings and the unanswered-questions log (FR-23).
 *
 * @package OrgChatbot
 */

defined( 'ABSPATH' ) || exit;

/**
 * Chatbot menu, settings form and log screen.
 */
class Org_Chatbot_Admin {

	const CAPABILITY = 'manage_options';
	const SLUG       = 'org-chatbot';

	/**
	 * Hook menus and actions.
	 */
	public static function init() {
		add_action( 'admin_menu', array( __CLASS__, 'menu' ) );
		add_action( 'admin_post_org_chatbot_log', array( __CLASS__, 'handle_log_action' ) );
	}

	/**
	 * Register the Chatbot menu.
	 */
	public static function menu() {
		add_menu_page( __( 'Chatbot', 'org-chatbot' ), __( 'Chatbot', 'org-chatbot' ), self::CAPABILITY, self::SLUG, array( __CLASS__, 'render_log' ), 'dashicons-format-chat', 26 );
		add_submenu_page( self::SLUG, __( 'Unanswered questions', 'org-chatbot' ), __( 'Unanswered questions', 'org-chatbot' ), self::CAPABILITY, self::SLUG, array( __CLASS__, 'render_log' ) );
		add_submenu_page( self::SLUG, __( 'Chatbot settings', 'org-chatbot' ), __( 'Settings', 'org-chatbot' ), self::CAPABILITY, self::SLUG . '-settings', array( __CLASS__, 'render_settings' ) );
	}

	/**
	 * Fetch the service health, cached briefly so the settings page stays fast.
	 *
	 * @return array|null
	 */
	private static function service_health() {
		$url = (string) Org_Chatbot_Settings::get( 'service_url' );
		if ( '' === $url ) {
			return null;
		}
		$health = get_transient( 'org_chatbot_health' );
		if ( false === $health ) {
			$response = wp_remote_get( $url . '/health', array( 'timeout' => 4 ) );
			$health   = is_wp_error( $response ) ? array( 'error' => $response->get_error_message() ) : json_decode( wp_remote_retrieve_body( $response ), true );
			set_transient( 'org_chatbot_health', is_array( $health ) ? $health : array( 'error' => 'invalid response' ), MINUTE_IN_SECONDS );
		}
		return is_array( $health ) ? $health : null;
	}

	/**
	 * Render the settings screen.
	 */
	public static function render_settings() {
		if ( ! current_user_can( self::CAPABILITY ) ) {
			return;
		}
		$s        = Org_Chatbot_Settings::all();
		$name     = Org_Chatbot_Settings::OPTION;
		$health   = self::service_health();
		$concerns = array_merge( (array) $s['concerns'], array_fill( 0, 2, array() ) );
		?>
		<div class="wrap">
			<h1><?php esc_html_e( 'Chatbot settings', 'org-chatbot' ); ?></h1>
			<?php settings_errors( $name ); ?>

			<?php if ( null !== $health ) : ?>
				<div class="notice <?php echo empty( $health['error'] ) ? 'notice-info' : 'notice-error'; ?> inline">
					<p>
						<?php if ( ! empty( $health['error'] ) ) : ?>
							<?php
							/* translators: %s: error message. */
							echo esc_html( sprintf( __( 'Chatbot service unreachable: %s', 'org-chatbot' ), $health['error'] ) );
							?>
						<?php else : ?>
							<?php
							echo esc_html(
								sprintf(
									/* translators: 1: number of FAQ entries, 2: matcher name. */
									__( 'Service connected: %1$d FAQ entries loaded, %2$s matcher.', 'org-chatbot' ),
									(int) ( $health['knowledge_base']['entries'] ?? 0 ),
									(string) ( $health['matcher']['name'] ?? '?' )
								)
							);
							echo ' ';
							if ( 'ready' === ( $health['asr']['state'] ?? '' ) ) {
								echo esc_html(
									sprintf(
										/* translators: 1: speech model, 2: encoder class. */
										__( 'Voice ready: %1$s (%2$s).', 'org-chatbot' ),
										(string) ( $health['asr']['model'] ?? '?' ),
										(string) ( $health['asr']['encoder'] ?? '?' )
									)
								);
							} else {
								echo esc_html(
									sprintf(
										/* translators: %s: speech model state, e.g. loading, disabled, error. */
										__( 'Voice: %s.', 'org-chatbot' ),
										trim( (string) ( $health['asr']['state'] ?? '?' ) . ' ' . (string) ( $health['asr']['error'] ?? '' ) )
									)
								);
							}
							?>
						<?php endif; ?>
					</p>
				</div>
			<?php endif; ?>

			<form method="post" action="options.php">
				<?php settings_fields( Org_Chatbot_Settings::GROUP ); ?>
				<h2><?php esc_html_e( 'Service', 'org-chatbot' ); ?></h2>
				<table class="form-table" role="presentation">
					<tr>
						<th scope="row"><?php esc_html_e( 'Widget', 'org-chatbot' ); ?></th>
						<td>
							<label><input type="checkbox" name="<?php echo esc_attr( $name ); ?>[widget_enabled]" value="1" <?php checked( $s['widget_enabled'] ); ?> /> <?php esc_html_e( 'Show the chatbot on public pages', 'org-chatbot' ); ?></label><br />
							<label><input type="checkbox" name="<?php echo esc_attr( $name ); ?>[voice_enabled]" value="1" <?php checked( $s['voice_enabled'] ); ?> /> <?php esc_html_e( 'Allow spoken questions (microphone button)', 'org-chatbot' ); ?></label>
						</td>
					</tr>
					<tr>
						<th scope="row"><label for="ocb-service"><?php esc_html_e( 'Chatbot service URL', 'org-chatbot' ); ?></label></th>
						<td><input id="ocb-service" type="url" class="regular-text" name="<?php echo esc_attr( $name ); ?>[service_url]" value="<?php echo esc_attr( $s['service_url'] ); ?>" placeholder="https://chatbot.example.org" /></td>
					</tr>
					<tr>
						<th scope="row"><label for="ocb-secret"><?php esc_html_e( 'Shared secret', 'org-chatbot' ); ?></label></th>
						<td>
							<?php if ( defined( 'ORG_CHATBOT_SHARED_SECRET' ) ) : ?>
								<p><?php esc_html_e( 'Set by ORG_CHATBOT_SHARED_SECRET in wp-config.php.', 'org-chatbot' ); ?></p>
							<?php else : ?>
								<input id="ocb-secret" type="password" class="regular-text" autocomplete="new-password" name="<?php echo esc_attr( $name ); ?>[shared_secret]" value="" placeholder="<?php echo '' !== $s['shared_secret'] ? esc_attr__( '(saved - leave blank to keep)', 'org-chatbot' ) : ''; ?>" />
								<p class="description"><?php esc_html_e( 'Must match WP_SHARED_SECRET in the service. Defining ORG_CHATBOT_SHARED_SECRET in wp-config.php is safer than saving it here.', 'org-chatbot' ); ?></p>
							<?php endif; ?>
						</td>
					</tr>
					<tr>
						<th scope="row"><label for="ocb-name"><?php esc_html_e( 'Chatbot name', 'org-chatbot' ); ?></label></th>
						<td><input id="ocb-name" type="text" class="regular-text" name="<?php echo esc_attr( $name ); ?>[bot_name]" value="<?php echo esc_attr( $s['bot_name'] ); ?>" /></td>
					</tr>
				</table>

				<h2><?php esc_html_e( 'Pages and messages', 'org-chatbot' ); ?></h2>
				<table class="form-table" role="presentation">
					<?php
					$pages = array(
						'faq_page_url'     => __( 'FAQ page URL', 'org-chatbot' ),
						'contact_page_url' => __( 'Contact page URL', 'org-chatbot' ),
						'privacy_page_url' => __( 'Privacy Notice URL (blank = site privacy policy)', 'org-chatbot' ),
					);
					foreach ( $pages as $key => $label ) :
						?>
						<tr>
							<th scope="row"><label for="ocb-<?php echo esc_attr( $key ); ?>"><?php echo esc_html( $label ); ?></label></th>
							<td><input id="ocb-<?php echo esc_attr( $key ); ?>" type="url" class="regular-text" name="<?php echo esc_attr( $name . '[' . $key . ']' ); ?>" value="<?php echo esc_attr( $s[ $key ] ); ?>" /></td>
						</tr>
					<?php endforeach; ?>
					<tr>
						<th scope="row"><label for="ocb-greeting"><?php esc_html_e( 'Greeting', 'org-chatbot' ); ?></label></th>
						<td><textarea id="ocb-greeting" class="large-text" rows="2" name="<?php echo esc_attr( $name ); ?>[greeting_message]"><?php echo esc_textarea( $s['greeting_message'] ); ?></textarea></td>
					</tr>
					<tr>
						<th scope="row"><label for="ocb-fallback"><?php esc_html_e( 'Fallback message', 'org-chatbot' ); ?></label></th>
						<td>
							<textarea id="ocb-fallback" class="large-text" rows="3" name="<?php echo esc_attr( $name ); ?>[fallback_message]"><?php echo esc_textarea( $s['fallback_message'] ); ?></textarea>
							<p class="description"><?php esc_html_e( 'Shown when no FAQ entry matches, followed by the inquiry email and links for the closest concern (FR-22).', 'org-chatbot' ); ?></p>
						</td>
					</tr>
				</table>

				<h2><?php esc_html_e( 'Inquiry concerns', 'org-chatbot' ); ?></h2>
				<p><?php esc_html_e( 'When the chatbot cannot answer, it offers the email and links of the concern whose keywords appear in the question, else the default concern. Concerns without an email are not offered. Clear the key to remove a row.', 'org-chatbot' ); ?></p>
				<style>.ocb-concerns { table-layout: fixed; } .ocb-concerns .ocb-cell { width: 100%; } .ocb-concerns th:first-child { width: 4.5em; } .ocb-concerns th:nth-child(2) { width: 9em; }</style>
				<table class="widefat striped ocb-concerns">
					<thead>
						<tr>
							<th><?php esc_html_e( 'Default', 'org-chatbot' ); ?></th>
							<th><?php esc_html_e( 'Key', 'org-chatbot' ); ?></th>
							<th><?php esc_html_e( 'Label', 'org-chatbot' ); ?></th>
							<th><?php esc_html_e( 'Inquiry email', 'org-chatbot' ); ?></th>
							<th><?php esc_html_e( 'Keywords (comma-separated)', 'org-chatbot' ); ?></th>
							<th><?php esc_html_e( 'Links (Label | URL per line)', 'org-chatbot' ); ?></th>
						</tr>
					</thead>
					<tbody>
					<?php foreach ( $concerns as $i => $c ) : ?>
						<?php $field = $name . '[concerns][' . (int) $i . ']'; ?>
						<tr>
							<td><input type="radio" name="<?php echo esc_attr( $name ); ?>[default_concern]" value="<?php echo esc_attr( $c['key'] ?? '' ); ?>" <?php checked( ( $c['key'] ?? '' ) !== '' && $s['default_concern'] === $c['key'] ); ?> aria-label="<?php esc_attr_e( 'Default concern', 'org-chatbot' ); ?>" /></td>
							<td><input type="text" class="ocb-cell ocb-key" name="<?php echo esc_attr( $field ); ?>[key]" value="<?php echo esc_attr( $c['key'] ?? '' ); ?>" aria-label="<?php esc_attr_e( 'Key', 'org-chatbot' ); ?>" /></td>
							<td><input type="text" class="ocb-cell" name="<?php echo esc_attr( $field ); ?>[label]" value="<?php echo esc_attr( $c['label'] ?? '' ); ?>" aria-label="<?php esc_attr_e( 'Label', 'org-chatbot' ); ?>" /></td>
							<td><input type="email" class="ocb-cell" name="<?php echo esc_attr( $field ); ?>[email]" value="<?php echo esc_attr( $c['email'] ?? '' ); ?>" aria-label="<?php esc_attr_e( 'Inquiry email', 'org-chatbot' ); ?>" /></td>
							<td><textarea rows="3" class="ocb-cell" name="<?php echo esc_attr( $field ); ?>[keywords]" aria-label="<?php esc_attr_e( 'Keywords', 'org-chatbot' ); ?>"><?php echo esc_textarea( implode( ', ', (array) ( $c['keywords'] ?? array() ) ) ); ?></textarea></td>
							<td><textarea rows="3" class="ocb-cell" name="<?php echo esc_attr( $field ); ?>[links]" aria-label="<?php esc_attr_e( 'Links', 'org-chatbot' ); ?>"><?php echo esc_textarea( Org_Chatbot_Settings::format_links( $c['links'] ?? array() ) ); ?></textarea></td>
						</tr>
					<?php endforeach; ?>
					</tbody>
				</table>

				<h2><?php esc_html_e( 'Knowledge base and privacy', 'org-chatbot' ); ?></h2>
				<table class="form-table" role="presentation">
					<tr>
						<th scope="row"><?php esc_html_e( 'FAQ source', 'org-chatbot' ); ?></th>
						<td>
							<label><input type="checkbox" name="<?php echo esc_attr( $name ); ?>[register_faq_type]" value="1" <?php checked( $s['register_faq_type'] ); ?> /> <?php esc_html_e( 'Provide the FAQ post type and categories (turn off if the theme already has them)', 'org-chatbot' ); ?></label><br />
							<label><?php esc_html_e( 'Post type', 'org-chatbot' ); ?> <input type="text" class="regular-text" name="<?php echo esc_attr( $name ); ?>[faq_post_type]" value="<?php echo esc_attr( $s['faq_post_type'] ); ?>" /></label><br />
							<label><?php esc_html_e( 'Category taxonomy', 'org-chatbot' ); ?> <input type="text" class="regular-text" name="<?php echo esc_attr( $name ); ?>[faq_taxonomy]" value="<?php echo esc_attr( $s['faq_taxonomy'] ); ?>" /></label>
						</td>
					</tr>
					<tr>
						<th scope="row"><label for="ocb-retention"><?php esc_html_e( 'Keep unanswered questions for', 'org-chatbot' ); ?></label></th>
						<td><input id="ocb-retention" type="number" min="1" max="365" class="small-text" name="<?php echo esc_attr( $name ); ?>[log_retention_days]" value="<?php echo esc_attr( (string) $s['log_retention_days'] ); ?>" /> <?php esc_html_e( 'days', 'org-chatbot' ); ?></td>
					</tr>
				</table>
				<?php submit_button(); ?>
			</form>
		</div>
		<?php
	}

	/**
	 * Render the unanswered-questions log.
	 */
	public static function render_log() {
		if ( ! current_user_can( self::CAPABILITY ) ) {
			return;
		}
		require_once ORG_CHATBOT_DIR . 'includes/class-org-chatbot-log-table.php';
		$table = new Org_Chatbot_Log_Table();
		$table->prepare_items();
		?>
		<div class="wrap">
			<h1><?php esc_html_e( 'Unanswered questions', 'org-chatbot' ); ?></h1>
			<p><?php esc_html_e( 'Questions the chatbot could not match to an FAQ entry. Names, emails, phone and ID numbers are masked before saving, and no visitor details are recorded. Turn frequent questions into FAQ entries, or add them as "other ways people ask" to an existing entry.', 'org-chatbot' ); ?></p>
			<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
				<input type="hidden" name="action" value="org_chatbot_log" />
				<?php wp_nonce_field( 'org_chatbot_log', 'org_chatbot_log_nonce' ); ?>
				<?php $table->display(); ?>
				<p><button type="submit" name="org_chatbot_do" value="clear" class="button" onclick="return confirm('<?php echo esc_js( __( 'Delete every logged question?', 'org-chatbot' ) ); ?>');"><?php esc_html_e( 'Clear the whole log', 'org-chatbot' ); ?></button></p>
			</form>
		</div>
		<?php
	}

	/**
	 * Handle delete and clear actions from the log screen.
	 */
	public static function handle_log_action() {
		if ( ! current_user_can( self::CAPABILITY ) ) {
			wp_die( esc_html__( 'You are not allowed to do that.', 'org-chatbot' ) );
		}
		check_admin_referer( 'org_chatbot_log', 'org_chatbot_log_nonce' );
		$do   = isset( $_POST['org_chatbot_do'] ) ? sanitize_key( wp_unslash( $_POST['org_chatbot_do'] ) ) : '';
		$bulk = isset( $_POST['org_chatbot_bulk'] ) ? sanitize_key( wp_unslash( $_POST['org_chatbot_bulk'] ) ) : '';
		if ( isset( $_POST['org_chatbot_delete'] ) ) {
			Org_Chatbot_Log::delete( array( absint( wp_unslash( $_POST['org_chatbot_delete'] ) ) ) );
		} elseif ( 'clear' === $do ) {
			Org_Chatbot_Log::clear();
		} elseif ( 'bulk' === $do && 'delete' === $bulk && isset( $_POST['ids'] ) ) {
			Org_Chatbot_Log::delete( array_map( 'absint', (array) wp_unslash( $_POST['ids'] ) ) );
		}
		wp_safe_redirect( admin_url( 'admin.php?page=' . self::SLUG ) );
		exit;
	}
}
