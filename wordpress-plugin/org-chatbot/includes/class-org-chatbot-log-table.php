<?php
/**
 * List table for the unanswered-questions log.
 *
 * @package OrgChatbot
 */

defined( 'ABSPATH' ) || exit;

if ( ! class_exists( 'WP_List_Table' ) ) {
	require_once ABSPATH . 'wp-admin/includes/class-wp-list-table.php';
}

/**
 * Unanswered questions with counts and dates (FR-23 AC2).
 */
class Org_Chatbot_Log_Table extends WP_List_Table {

	/**
	 * Set up the table.
	 */
	public function __construct() {
		parent::__construct(
			array(
				'singular' => 'question',
				'plural'   => 'questions',
				'ajax'     => false,
			)
		);
	}

	/**
	 * Columns.
	 *
	 * @return array
	 */
	public function get_columns() {
		return array(
			'cb'           => '<input type="checkbox" />',
			'question'     => __( 'Question', 'org-chatbot' ),
			'times_asked'  => __( 'Times asked', 'org-chatbot' ),
			'times_spoken' => __( 'Of which spoken', 'org-chatbot' ),
			'first_asked'  => __( 'First asked', 'org-chatbot' ),
			'last_asked'   => __( 'Last asked', 'org-chatbot' ),
		);
	}

	/**
	 * Sortable columns.
	 *
	 * @return array
	 */
	protected function get_sortable_columns() {
		return array(
			'times_asked' => array( 'times_asked', true ),
			'first_asked' => array( 'first_asked', false ),
			'last_asked'  => array( 'last_asked', true ),
		);
	}

	/**
	 * Load the current page of rows.
	 */
	public function prepare_items() {
		// phpcs:disable WordPress.Security.NonceVerification.Recommended -- read-only sorting and paging.
		$orderby = isset( $_GET['orderby'] ) ? sanitize_key( wp_unslash( $_GET['orderby'] ) ) : 'last_asked';
		$order   = isset( $_GET['order'] ) ? sanitize_key( wp_unslash( $_GET['order'] ) ) : 'desc';
		// phpcs:enable
		$per_page = 30;
		$page     = $this->get_pagenum();
		$result   = Org_Chatbot_Log::page( $orderby, $order, $per_page, $page );

		$this->items           = $result['rows'];
		$this->_column_headers = array( $this->get_columns(), array(), $this->get_sortable_columns() );
		$this->set_pagination_args(
			array(
				'total_items' => $result['total'],
				'per_page'    => $per_page,
			)
		);
	}

	/**
	 * Our own bulk control; the built-in one would clash with admin-post.php's "action" field.
	 *
	 * @param string $which Top or bottom.
	 */
	protected function extra_tablenav( $which ) {
		if ( 'top' !== $which ) {
			return;
		}
		?>
		<div class="alignleft actions">
			<label class="screen-reader-text" for="org-chatbot-bulk"><?php esc_html_e( 'Bulk action', 'org-chatbot' ); ?></label>
			<select id="org-chatbot-bulk" name="org_chatbot_bulk">
				<option value=""><?php esc_html_e( 'Bulk actions', 'org-chatbot' ); ?></option>
				<option value="delete"><?php esc_html_e( 'Delete', 'org-chatbot' ); ?></option>
			</select>
			<button type="submit" class="button" name="org_chatbot_do" value="bulk"><?php esc_html_e( 'Apply', 'org-chatbot' ); ?></button>
		</div>
		<?php
	}

	/**
	 * Checkbox column.
	 *
	 * @param array $item Row.
	 * @return string
	 */
	protected function column_cb( $item ) {
		return sprintf( '<input type="checkbox" name="ids[]" value="%d" />', (int) $item['id'] );
	}

	/**
	 * Question column with row actions.
	 *
	 * @param array $item Row.
	 * @return string
	 */
	protected function column_question( $item ) {
		$new_faq = wp_nonce_url(
			add_query_arg(
				array(
					'post_type'            => Org_Chatbot_Settings::get( 'faq_post_type' ),
					'org_chatbot_question' => rawurlencode( $item['question'] ),
				),
				admin_url( 'post-new.php' )
			),
			'org_chatbot_new_faq'
		);
		$actions = array(
			'create' => sprintf( '<a href="%s">%s</a>', esc_url( $new_faq ), esc_html__( 'Create FAQ entry', 'org-chatbot' ) ),
			'delete' => sprintf(
				'<button type="submit" class="button-link button-link-delete" name="org_chatbot_delete" value="%d">%s</button>',
				(int) $item['id'],
				esc_html__( 'Delete', 'org-chatbot' )
			),
		);
		return esc_html( $item['question'] ) . $this->row_actions( $actions );
	}

	/**
	 * Other columns; dates are stored in UTC and shown in the site's time zone.
	 *
	 * @param array  $item        Row.
	 * @param string $column_name Column.
	 * @return string
	 */
	protected function column_default( $item, $column_name ) {
		if ( in_array( $column_name, array( 'first_asked', 'last_asked' ), true ) ) {
			$format = get_option( 'date_format' ) . ' ' . get_option( 'time_format' );
			return esc_html( get_date_from_gmt( $item[ $column_name ], $format ) );
		}
		return esc_html( (string) ( $item[ $column_name ] ?? '' ) );
	}

	/**
	 * Message when the log is empty.
	 */
	public function no_items() {
		esc_html_e( 'No unanswered questions yet.', 'org-chatbot' );
	}
}
