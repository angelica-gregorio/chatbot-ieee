<?php
$_SERVER['HTTP_HOST'] = '127.0.0.1:8090';
require getenv( 'WP_TEST_DIR' ) . '/site/wp-load.php';
require_once ABSPATH . 'wp-admin/includes/plugin.php';
wp_set_current_user( 1 );

update_option( 'permalink_structure', '/%postname%/' );

// Settings go through the plugin's own sanitizer, exactly like the settings form.
$kb  = json_decode( file_get_contents( getenv( 'REPO_ROOT' ) . '/chatbot-service/eval/data/sample_kb.json' ), true );
$raw = array(
	'widget_enabled' => '1', 'voice_enabled' => '1', 'register_faq_type' => '1',
	'service_url' => 'http://127.0.0.1:8000/', 'faq_page_url' => 'http://127.0.0.1:8090/faq/',
	'contact_page_url' => 'https://example.org/contact/', 'privacy_page_url' => '',
	'faq_post_type' => 'org_faq', 'faq_taxonomy' => 'org_faq_category', 'bot_name' => 'Ask us',
	'greeting_message' => $kb['greeting_message'], 'fallback_message' => $kb['fallback_message'],
	'default_concern' => 'general', 'log_retention_days' => '90', 'concerns' => array(),
);
foreach ( $kb['concerns'] as $c ) {
	$raw['concerns'][] = array(
		'key' => $c['key'], 'label' => $c['label'], 'email' => $c['email'],
		'keywords' => implode( ', ', $c['keywords'] ),
		'links' => implode( "\n", array_map( fn( $l ) => $l['label'] . ' | ' . $l['url'], $c['links'] ) ),
	);
}
$raw['concerns'][] = array( 'key' => 'bad', 'label' => 'Bad', 'email' => 'not-an-email', 'keywords' => '', 'links' => 'x | javascript:alert(1)' );
$once = Org_Chatbot_Settings::sanitize( $raw );
echo 'sanitize idempotent: ', ( Org_Chatbot_Settings::sanitize( $once ) === $once ) ? 'yes' : 'NO', PHP_EOL;
update_option( 'org_chatbot_settings', $once );
$saved = Org_Chatbot_Settings::all();
echo 'events keywords: ', implode( ',', $saved['concerns'][1]['keywords'] ), ' | events links: ', count( $saved['concerns'][1]['links'] ), PHP_EOL;
echo 'service_url: ', $saved['service_url'], ' | concerns: ', count( $saved['concerns'] ), ' | bad email kept: ', var_export( end( $saved['concerns'] )['email'], true ), ' | bad link kept: ', count( end( $saved['concerns'] )['links'] ), PHP_EOL;

// FAQ entries.
echo 'taxonomy registered: ', taxonomy_exists( 'org_faq_category' ) ? 'yes' : 'no', PHP_EOL;
foreach ( $kb['entries'] as $e ) {
	$term = term_exists( $e['category'], 'org_faq_category' ) ?: wp_insert_term( $e['category'], 'org_faq_category' );
	update_term_meta( (int) $term['term_id'], 'org_chatbot_concern', $e['concern'] );
	$id = wp_insert_post( array( 'post_type' => 'org_faq', 'post_status' => 'publish', 'post_title' => $e['question'], 'post_content' => $e['answer_html'] ) );
	wp_set_object_terms( $id, (int) $term['term_id'], 'org_faq_category' );
	update_post_meta( $id, '_org_chatbot_alt_questions', implode( "\n", $e['alt_questions'] ) );
	update_post_meta( $id, '_org_chatbot_links', implode( "\n", array_map( fn( $l ) => $l['label'] . ' | ' . $l['url'], $e['links'] ) ) );
}
// A disabled entry that must NOT reach the chatbot (FR-23 "disable").
$hidden = wp_insert_post( array( 'post_type' => 'org_faq', 'post_status' => 'publish', 'post_title' => 'What is the secret handshake?', 'post_content' => 'Internal only.' ) );
update_post_meta( $hidden, '_org_chatbot_enabled', '0' );
wp_insert_post( array( 'post_type' => 'page', 'post_status' => 'publish', 'post_title' => 'FAQ', 'post_name' => 'faq', 'post_content' => '[org_faq]' ) );
delete_transient( 'org_chatbot_kb' );
flush_rewrite_rules();
global $wpdb;
echo 'faq posts: ', count( get_posts( array( 'post_type' => 'org_faq', 'numberposts' => -1 ) ) ), ' | log table: ', $wpdb->get_var( "SELECT COUNT(*) FROM {$wpdb->prefix}org_chatbot_unanswered" ), ' rows', PHP_EOL;
echo 'cron scheduled: ', wp_next_scheduled( 'org_chatbot_purge_log' ) ? 'yes' : 'no', PHP_EOL;
