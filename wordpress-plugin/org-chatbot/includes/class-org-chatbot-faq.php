<?php
/**
 * FAQ entries as the chatbot's knowledge base (FR-17, FR-23).
 *
 * Registers the FAQ post type and category taxonomy unless the site already
 * has them, adds a "Chatbot" box to each entry (use in chatbot, other ways
 * people ask, related links), maps each category to an inquiry concern, and
 * provides the [org_faq] shortcode for the FAQ page.
 *
 * @package OrgChatbot
 */

defined( 'ABSPATH' ) || exit;

/**
 * FAQ post type, fields and shortcode.
 */
class Org_Chatbot_Faq {

	const META_ENABLED       = '_org_chatbot_enabled';
	const META_ALT_QUESTIONS = '_org_chatbot_alt_questions';
	const META_LINKS         = '_org_chatbot_links';
	const TERM_CONCERN       = 'org_chatbot_concern';
	const NONCE              = 'org_chatbot_faq_meta';

	/**
	 * Hook everything.
	 */
	public static function init() {
		add_action( 'init', array( __CLASS__, 'register_types' ) );
		add_action( 'add_meta_boxes', array( __CLASS__, 'add_meta_box' ) );
		add_action( 'save_post', array( __CLASS__, 'save_meta' ), 10, 2 );
		add_filter( 'default_title', array( __CLASS__, 'prefill_title' ), 10, 2 );
		add_shortcode( 'org_faq', array( __CLASS__, 'shortcode' ) );

		$taxonomy = (string) Org_Chatbot_Settings::get( 'faq_taxonomy' );
		add_action( "{$taxonomy}_add_form_fields", array( __CLASS__, 'term_add_field' ) );
		add_action( "{$taxonomy}_edit_form_fields", array( __CLASS__, 'term_edit_field' ) );
		add_action( "created_{$taxonomy}", array( __CLASS__, 'save_term' ) );
		add_action( "edited_{$taxonomy}", array( __CLASS__, 'save_term' ) );
	}

	/**
	 * FAQ post type slug.
	 *
	 * @return string
	 */
	private static function post_type() {
		return (string) Org_Chatbot_Settings::get( 'faq_post_type' );
	}

	/**
	 * Register the FAQ type and category unless they already exist.
	 */
	public static function register_types() {
		if ( ! Org_Chatbot_Settings::get( 'register_faq_type' ) ) {
			return;
		}
		$post_type = self::post_type();
		$taxonomy  = (string) Org_Chatbot_Settings::get( 'faq_taxonomy' );
		if ( ! post_type_exists( $post_type ) ) {
			register_post_type(
				$post_type,
				array(
					'labels'       => array(
						'name'          => __( 'FAQs', 'org-chatbot' ),
						'singular_name' => __( 'FAQ', 'org-chatbot' ),
						'add_new_item'  => __( 'Add FAQ entry', 'org-chatbot' ),
						'edit_item'     => __( 'Edit FAQ entry', 'org-chatbot' ),
						'menu_name'     => __( 'FAQs', 'org-chatbot' ),
					),
					'public'       => false,
					'show_ui'      => true,
					'show_in_rest' => true,
					'menu_icon'    => 'dashicons-editor-help',
					'supports'     => array( 'title', 'editor', 'page-attributes', 'revisions' ),
					'map_meta_cap' => true,
				)
			);
		}
		if ( ! taxonomy_exists( $taxonomy ) ) {
			register_taxonomy(
				$taxonomy,
				$post_type,
				array(
					'labels'            => array(
						'name'          => __( 'FAQ categories', 'org-chatbot' ),
						'singular_name' => __( 'FAQ category', 'org-chatbot' ),
					),
					'public'            => false,
					'show_ui'           => true,
					'show_in_rest'      => true,
					'show_admin_column' => true,
					'hierarchical'      => true,
				)
			);
		}
	}

	/**
	 * Add the Chatbot box to FAQ entries.
	 */
	public static function add_meta_box() {
		add_meta_box( 'org-chatbot', __( 'Chatbot', 'org-chatbot' ), array( __CLASS__, 'render_meta_box' ), self::post_type(), 'normal', 'high' );
	}

	/**
	 * Render the Chatbot box.
	 *
	 * @param WP_Post $post FAQ entry.
	 */
	public static function render_meta_box( $post ) {
		wp_nonce_field( self::NONCE, self::NONCE );
		$enabled = get_post_meta( $post->ID, self::META_ENABLED, true );
		$alts    = (string) get_post_meta( $post->ID, self::META_ALT_QUESTIONS, true );
		$links   = (string) get_post_meta( $post->ID, self::META_LINKS, true );
		?>
		<p>
			<label>
				<input type="checkbox" name="org_chatbot_enabled" value="1" <?php checked( '0' !== $enabled ); ?> />
				<?php esc_html_e( 'The chatbot may give this answer', 'org-chatbot' ); ?>
			</label>
		</p>
		<p>
			<label for="org-chatbot-alt"><strong><?php esc_html_e( 'Other ways people ask this', 'org-chatbot' ); ?></strong></label><br />
			<textarea id="org-chatbot-alt" name="org_chatbot_alt_questions" rows="4" class="large-text" placeholder="<?php esc_attr_e( 'One question per line, e.g. How can I join?', 'org-chatbot' ); ?>"><?php echo esc_textarea( $alts ); ?></textarea>
			<span class="description"><?php esc_html_e( 'Each extra phrasing helps the chatbot recognise reworded and spoken questions. The title is the main question; the content is the answer.', 'org-chatbot' ); ?></span>
		</p>
		<p>
			<label for="org-chatbot-links"><strong><?php esc_html_e( 'Related links', 'org-chatbot' ); ?></strong></label><br />
			<textarea id="org-chatbot-links" name="org_chatbot_links" rows="3" class="large-text" placeholder="Events | https://example.org/events/"><?php echo esc_textarea( $links ); ?></textarea>
			<span class="description"><?php esc_html_e( 'One per line: Label | URL. Shown under the answer.', 'org-chatbot' ); ?></span>
		</p>
		<?php
	}

	/**
	 * Save the Chatbot box.
	 *
	 * @param int     $post_id Post id.
	 * @param WP_Post $post    Post.
	 */
	public static function save_meta( $post_id, $post ) {
		if ( self::post_type() !== $post->post_type || wp_is_post_autosave( $post_id ) || wp_is_post_revision( $post_id ) ) {
			return;
		}
		$nonce = isset( $_POST[ self::NONCE ] ) ? sanitize_text_field( wp_unslash( $_POST[ self::NONCE ] ) ) : '';
		if ( ! wp_verify_nonce( $nonce, self::NONCE ) || ! current_user_can( 'edit_post', $post_id ) ) {
			return;
		}
		update_post_meta( $post_id, self::META_ENABLED, isset( $_POST['org_chatbot_enabled'] ) ? '1' : '0' );
		$alts = isset( $_POST['org_chatbot_alt_questions'] ) ? sanitize_textarea_field( wp_unslash( $_POST['org_chatbot_alt_questions'] ) ) : '';
		update_post_meta( $post_id, self::META_ALT_QUESTIONS, $alts );
		$links = isset( $_POST['org_chatbot_links'] ) ? sanitize_textarea_field( wp_unslash( $_POST['org_chatbot_links'] ) ) : '';
		update_post_meta( $post_id, self::META_LINKS, Org_Chatbot_Settings::format_links( Org_Chatbot_Settings::parse_links( $links ) ) );
		Org_Chatbot_Knowledge_Base::mark_dirty();
	}

	/**
	 * Pre-fill a new FAQ title from the unanswered-questions log.
	 *
	 * @param string  $title Default title.
	 * @param WP_Post $post  New post.
	 * @return string
	 */
	public static function prefill_title( $title, $post ) {
		if ( self::post_type() !== $post->post_type || ! isset( $_GET['org_chatbot_question'], $_GET['_wpnonce'] ) ) {
			return $title;
		}
		if ( ! wp_verify_nonce( sanitize_text_field( wp_unslash( $_GET['_wpnonce'] ) ), 'org_chatbot_new_faq' ) ) {
			return $title;
		}
		return sanitize_text_field( wp_unslash( $_GET['org_chatbot_question'] ) );
	}

	/**
	 * Concern options for the category screens.
	 *
	 * @param string $selected Selected concern key.
	 */
	private static function concern_options( $selected ) {
		echo '<option value="">' . esc_html__( 'Default concern', 'org-chatbot' ) . '</option>';
		foreach ( (array) Org_Chatbot_Settings::get( 'concerns' ) as $concern ) {
			printf(
				'<option value="%1$s" %2$s>%3$s</option>',
				esc_attr( $concern['key'] ),
				selected( $selected, $concern['key'], false ),
				esc_html( $concern['label'] )
			);
		}
	}

	/**
	 * Concern field on "Add category".
	 */
	public static function term_add_field() {
		wp_nonce_field( 'org_chatbot_term', 'org_chatbot_term_nonce' );
		?>
		<div class="form-field">
			<label for="org-chatbot-concern"><?php esc_html_e( 'Chatbot inquiry concern', 'org-chatbot' ); ?></label>
			<select id="org-chatbot-concern" name="org_chatbot_concern"><?php self::concern_options( '' ); ?></select>
			<p><?php esc_html_e( 'Which inquiry email the chatbot offers when a question near this category cannot be answered.', 'org-chatbot' ); ?></p>
		</div>
		<?php
	}

	/**
	 * Concern field on "Edit category".
	 *
	 * @param WP_Term $term Category.
	 */
	public static function term_edit_field( $term ) {
		wp_nonce_field( 'org_chatbot_term', 'org_chatbot_term_nonce' );
		?>
		<tr class="form-field">
			<th scope="row"><label for="org-chatbot-concern"><?php esc_html_e( 'Chatbot inquiry concern', 'org-chatbot' ); ?></label></th>
			<td><select id="org-chatbot-concern" name="org_chatbot_concern"><?php self::concern_options( (string) get_term_meta( $term->term_id, self::TERM_CONCERN, true ) ); ?></select></td>
		</tr>
		<?php
	}

	/**
	 * Save the category's concern.
	 *
	 * @param int $term_id Term id.
	 */
	public static function save_term( $term_id ) {
		$nonce = isset( $_POST['org_chatbot_term_nonce'] ) ? sanitize_text_field( wp_unslash( $_POST['org_chatbot_term_nonce'] ) ) : '';
		if ( ! wp_verify_nonce( $nonce, 'org_chatbot_term' ) || ! current_user_can( 'manage_categories' ) ) {
			return;
		}
		$concern = isset( $_POST['org_chatbot_concern'] ) ? sanitize_key( wp_unslash( $_POST['org_chatbot_concern'] ) ) : '';
		update_term_meta( $term_id, self::TERM_CONCERN, $concern );
	}

	/**
	 * [org_faq] - FAQ page grouped by category. Answers open with click, Enter or Space (FR-17 AC1).
	 *
	 * @return string
	 */
	public static function shortcode() {
		$taxonomy = (string) Org_Chatbot_Settings::get( 'faq_taxonomy' );
		$posts    = get_posts(
			array(
				'post_type'        => self::post_type(),
				'post_status'      => 'publish',
				'numberposts'      => -1,
				'orderby'          => array(
					'menu_order' => 'ASC',
					'title'      => 'ASC',
				),
				'suppress_filters' => false,
			)
		);
		$groups   = array();
		foreach ( $posts as $post ) {
			$terms             = get_the_terms( $post, $taxonomy );
			$name              = is_array( $terms ) && $terms ? $terms[0]->name : __( 'General', 'org-chatbot' );
			$groups[ $name ][] = $post;
		}
		ob_start();
		echo '<div class="org-faq">';
		foreach ( $groups as $name => $items ) {
			echo '<h2 class="org-faq__category">' . esc_html( $name ) . '</h2>';
			foreach ( $items as $post ) {
				printf(
					'<details class="org-faq__item" id="faq-%1$d"><summary>%2$s</summary><div class="org-faq__answer">%3$s</div></details>',
					(int) $post->ID,
					esc_html( get_the_title( $post ) ),
					wp_kses_post( Org_Chatbot_Knowledge_Base::answer_html( $post ) )
				);
			}
		}
		echo '</div>';
		return (string) ob_get_clean();
	}
}
