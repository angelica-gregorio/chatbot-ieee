<?php
define( 'WP_INSTALLING', true );
$_SERVER['HTTP_HOST'] = '127.0.0.1:8090';
require getenv( 'WP_TEST_DIR' ) . '/site/wp-load.php';
require_once ABSPATH . 'wp-admin/includes/upgrade.php';
$r = wp_install( 'Organization (test)', 'admin', 'admin@example.org', false, '', 'local-test-pass-123' );
echo 'installed user ', $r['user_id'], PHP_EOL;
