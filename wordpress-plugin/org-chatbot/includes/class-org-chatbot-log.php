<?php
/**
 * Log of questions the chatbot could not answer (FR-23 AC2).
 *
 * Stores only the redacted question text, how often it was asked (typed and
 * spoken), and when it was first and last asked. No IP address, name, email,
 * session or audio is stored. Entries older than the retention period are
 * deleted daily.
 *
 * @package OrgChatbot
 */

defined( 'ABSPATH' ) || exit;

/**
 * Custom table for unanswered questions.
 */
class Org_Chatbot_Log {

	const DB_VERSION = '1';
	const CRON_HOOK  = 'org_chatbot_purge_log';

	/**
	 * Hook the purge job and upgrade the table if needed.
	 */
	public static function init() {
		add_action( self::CRON_HOOK, array( __CLASS__, 'purge' ) );
		if ( get_option( 'org_chatbot_db_version' ) !== self::DB_VERSION ) {
			self::install();
		}
	}

	/**
	 * Table name.
	 *
	 * @return string
	 */
	public static function table() {
		global $wpdb;
		return $wpdb->prefix . 'org_chatbot_unanswered';
	}

	/**
	 * Activation: create the table and schedule the daily purge.
	 */
	public static function activate() {
		self::install();
		if ( ! wp_next_scheduled( self::CRON_HOOK ) ) {
			wp_schedule_event( time() + HOUR_IN_SECONDS, 'daily', self::CRON_HOOK );
		}
	}

	/**
	 * Deactivation: stop the purge job (data stays until uninstall).
	 */
	public static function deactivate() {
		wp_clear_scheduled_hook( self::CRON_HOOK );
	}

	/**
	 * Create or upgrade the table.
	 */
	public static function install() {
		global $wpdb;
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';
		$table   = self::table();
		$charset = $wpdb->get_charset_collate();
		dbDelta(
			"CREATE TABLE {$table} (
				id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
				question_hash char(40) NOT NULL,
				question varchar(300) NOT NULL,
				times_asked int(10) unsigned NOT NULL DEFAULT 1,
				times_spoken int(10) unsigned NOT NULL DEFAULT 0,
				first_asked datetime NOT NULL,
				last_asked datetime NOT NULL,
				PRIMARY KEY  (id),
				UNIQUE KEY question_hash (question_hash),
				KEY last_asked (last_asked)
			) {$charset};"
		);
		update_option( 'org_chatbot_db_version', self::DB_VERSION, false );
	}

	/**
	 * Normalise a question so rephrasings with different punctuation or case count together.
	 *
	 * @param string $question Redacted question.
	 * @return string
	 */
	public static function hash( $question ) {
		$normal = strtolower( trim( preg_replace( '/[^\p{L}\p{N}\[\]]+/u', ' ', $question ) ) );
		return sha1( $normal );
	}

	/**
	 * Record one unanswered question.
	 *
	 * @param string $question Question text (redacted again here).
	 * @param string $source   "text" or "voice".
	 * @return bool
	 */
	public static function record( $question, $source = 'text' ) {
		global $wpdb;
		$question = mb_substr( Org_Chatbot_Redactor::redact( sanitize_textarea_field( $question ) ), 0, 300 );
		if ( '' === $question ) {
			return false;
		}
		$now    = current_time( 'mysql', true );
		$spoken = 'voice' === $source ? 1 : 0;
		// phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching -- custom table, write path.
		$result = $wpdb->query(
			$wpdb->prepare(
				'INSERT INTO %i (question_hash, question, times_asked, times_spoken, first_asked, last_asked)
				VALUES (%s, %s, 1, %d, %s, %s)
				ON DUPLICATE KEY UPDATE times_asked = times_asked + 1, times_spoken = times_spoken + %d, last_asked = %s',
				self::table(),
				self::hash( $question ),
				$question,
				$spoken,
				$now,
				$now,
				$spoken,
				$now
			)
		);
		return false !== $result;
	}

	/**
	 * Delete entries not asked within the retention period.
	 */
	public static function purge() {
		global $wpdb;
		$days   = (int) Org_Chatbot_Settings::get( 'log_retention_days' );
		$cutoff = gmdate( 'Y-m-d H:i:s', time() - max( 1, $days ) * DAY_IN_SECONDS );
		// phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching -- custom table, scheduled cleanup.
		$wpdb->query( $wpdb->prepare( 'DELETE FROM %i WHERE last_asked < %s', self::table(), $cutoff ) );
	}

	/**
	 * Delete entries by id.
	 *
	 * @param int[] $ids Row ids.
	 */
	public static function delete( $ids ) {
		global $wpdb;
		$ids = array_filter( array_map( 'absint', (array) $ids ) );
		foreach ( $ids as $id ) {
			// phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching -- custom table, admin action.
			$wpdb->delete( self::table(), array( 'id' => $id ), array( '%d' ) );
		}
	}

	/**
	 * Delete everything.
	 */
	public static function clear() {
		global $wpdb;
		// phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching, WordPress.DB.DirectDatabaseQuery.SchemaChange -- custom table, admin action.
		$wpdb->query( $wpdb->prepare( 'TRUNCATE TABLE %i', self::table() ) );
	}

	/**
	 * A page of rows for the admin list.
	 *
	 * @param string $orderby  times_asked, last_asked or first_asked.
	 * @param string $order    ASC or DESC.
	 * @param int    $per_page Rows per page.
	 * @param int    $page     1-based page.
	 * @return array{rows: array, total: int}
	 */
	public static function page( $orderby, $order, $per_page, $page ) {
		global $wpdb;
		$orderby = in_array( $orderby, array( 'times_asked', 'last_asked', 'first_asked' ), true ) ? $orderby : 'last_asked';
		$order   = 'ASC' === strtoupper( $order ) ? 'ASC' : 'DESC';
		$offset  = max( 0, ( $page - 1 ) * $per_page );
		// phpcs:disable WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching -- custom table, admin screen.
		$total = (int) $wpdb->get_var( $wpdb->prepare( 'SELECT COUNT(*) FROM %i', self::table() ) );
		$rows  = $wpdb->get_results(
			$wpdb->prepare(
				// The ORDER BY column and direction are whitelisted above.
				"SELECT id, question, times_asked, times_spoken, first_asked, last_asked FROM %i ORDER BY %i {$order} LIMIT %d OFFSET %d", // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
				self::table(),
				$orderby,
				$per_page,
				$offset
			),
			ARRAY_A
		);
		// phpcs:enable
		return array(
			'rows'  => $rows ? $rows : array(),
			'total' => $total,
		);
	}
}
