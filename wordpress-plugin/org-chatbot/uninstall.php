<?php
/**
 * Uninstall: remove the plugin's settings, log table and chatbot fields.
 * FAQ entries themselves are site content and are kept.
 *
 * @package OrgChatbot
 */

defined( 'WP_UNINSTALL_PLUGIN' ) || exit;

global $wpdb;

delete_option( 'org_chatbot_settings' );
delete_option( 'org_chatbot_db_version' );
delete_transient( 'org_chatbot_kb' );
delete_transient( 'org_chatbot_health' );
wp_clear_scheduled_hook( 'org_chatbot_purge_log' );

// phpcs:disable WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching, WordPress.DB.DirectDatabaseQuery.SchemaChange -- one-time cleanup of the plugin's own data.
$wpdb->query( $wpdb->prepare( 'DROP TABLE IF EXISTS %i', $wpdb->prefix . 'org_chatbot_unanswered' ) );
$wpdb->query( $wpdb->prepare( "DELETE FROM {$wpdb->postmeta} WHERE meta_key IN (%s, %s, %s)", '_org_chatbot_enabled', '_org_chatbot_alt_questions', '_org_chatbot_links' ) );
$wpdb->query( $wpdb->prepare( "DELETE FROM {$wpdb->termmeta} WHERE meta_key = %s", 'org_chatbot_concern' ) );
// phpcs:enable
