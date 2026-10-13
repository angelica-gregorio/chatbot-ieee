<?php
define( 'DB_NAME', 'wp' );
define( 'DB_USER', 'wp' );
define( 'DB_PASSWORD', 'wp' );
define( 'DB_HOST', 'localhost' );
define( 'DB_CHARSET', 'utf8mb4' );
define( 'DB_COLLATE', '' );
$table_prefix = 'wp_';
define( 'WP_HOME', 'http://127.0.0.1:8090' );
define( 'WP_SITEURL', 'http://127.0.0.1:8090' );
define( 'WP_DEBUG', true );
define( 'WP_DEBUG_LOG', true );
define( 'WP_DEBUG_DISPLAY', false );
define( 'ORG_CHATBOT_SHARED_SECRET', 'test-secret' ); // Test value for this throwaway site only.
define( 'AUTH_KEY', 'k1' ); define( 'SECURE_AUTH_KEY', 'k2' ); define( 'LOGGED_IN_KEY', 'k3' ); define( 'NONCE_KEY', 'k4' );
define( 'AUTH_SALT', 's1' ); define( 'SECURE_AUTH_SALT', 's2' ); define( 'LOGGED_IN_SALT', 's3' ); define( 'NONCE_SALT', 's4' );
if ( ! defined( 'ABSPATH' ) ) { define( 'ABSPATH', __DIR__ . '/' ); }
require_once ABSPATH . 'wp-settings.php';
