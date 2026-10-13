<?php
$_SERVER['HTTP_HOST'] = '127.0.0.1:8090';
require getenv( 'WP_TEST_DIR' ) . '/site/wp-load.php';
global $wpdb;
echo wp_json_encode( $wpdb->get_results( "SELECT question, times_asked, times_spoken FROM {$wpdb->prefix}org_chatbot_unanswered ORDER BY id", ARRAY_A ) );
