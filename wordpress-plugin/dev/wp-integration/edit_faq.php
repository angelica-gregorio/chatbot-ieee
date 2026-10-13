<?php
// Simulates an administrator editing an FAQ answer (runs WordPress hooks, including the refresh webhook).
$_SERVER['HTTP_HOST'] = '127.0.0.1:8090';
require getenv( 'WP_TEST_DIR' ) . '/site/wp-load.php';
wp_set_current_user( 1 );
$post = get_page_by_title( 'How do I become a member?', OBJECT, 'org_faq' );
wp_update_post( array( 'ID' => $post->ID, 'post_content' => '<p>Edited via WordPress: see the Join page.</p>' ) );
echo $post->ID;
