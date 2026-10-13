<?php
/**
 * Router for PHP's built-in server: pretty permalinks and the REST API for the test site.
 * Start with: php -S 127.0.0.1:8090 -t "$WP_TEST_DIR/site" router.php
 *
 * @package OrgChatbot
 */

$org_site = getenv( 'WP_TEST_DIR' ) . '/site';
$org_path = (string) parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH ); // phpcs:ignore
$org_file = $org_site . $org_path;
if ( '/' !== $org_path && is_file( $org_file ) && ! preg_match( '/\.php$/', $org_file ) ) {
	return false; // Static file: served from the -t document root.
}
if ( is_file( $org_file ) && preg_match( '/\.php$/', $org_file ) ) {
	chdir( dirname( $org_file ) );
	require $org_file;
	return;
}
if ( is_dir( $org_file ) && is_file( rtrim( $org_file, '/' ) . '/index.php' ) ) {
	chdir( rtrim( $org_file, '/' ) );
	require rtrim( $org_file, '/' ) . '/index.php';
	return;
}
chdir( $org_site );
require $org_site . '/index.php';
