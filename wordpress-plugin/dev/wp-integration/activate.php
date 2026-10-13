<?php
$_SERVER['HTTP_HOST'] = '127.0.0.1:8090';
require getenv( 'WP_TEST_DIR' ) . '/site/wp-load.php';
require_once ABSPATH . 'wp-admin/includes/plugin.php';
wp_set_current_user( 1 );

$res = activate_plugin( 'org-chatbot/org-chatbot.php' );
echo 'activate: ', is_wp_error( $res ) ? $res->get_error_message() : 'ok', PHP_EOL;
