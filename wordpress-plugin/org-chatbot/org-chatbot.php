<?php
/**
 * Plugin Name:       Organization FAQ Chatbot
 * Description:       FAQ chatbot for the Organization website. Answers typed and spoken questions using only the approved FAQ entries; spoken questions are transcribed by an E-Branchformer speech model in the companion chatbot service.
 * Version:           0.2.0
 * Requires at least: 6.4
 * Requires PHP:      8.1
 * Author:            CPECAPS project team
 * License:           GPL-2.0-or-later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       org-chatbot
 *
 * @package OrgChatbot
 */

defined( 'ABSPATH' ) || exit;

define( 'ORG_CHATBOT_VERSION', '0.2.0' );
define( 'ORG_CHATBOT_FILE', __FILE__ );
define( 'ORG_CHATBOT_DIR', plugin_dir_path( __FILE__ ) );
define( 'ORG_CHATBOT_URL', plugin_dir_url( __FILE__ ) );

require_once ORG_CHATBOT_DIR . 'includes/class-org-chatbot-settings.php';
require_once ORG_CHATBOT_DIR . 'includes/class-org-chatbot-redactor.php';
require_once ORG_CHATBOT_DIR . 'includes/class-org-chatbot-log.php';
require_once ORG_CHATBOT_DIR . 'includes/class-org-chatbot-knowledge-base.php';
require_once ORG_CHATBOT_DIR . 'includes/class-org-chatbot-faq.php';
require_once ORG_CHATBOT_DIR . 'includes/class-org-chatbot-rest.php';
require_once ORG_CHATBOT_DIR . 'includes/class-org-chatbot-widget.php';
require_once ORG_CHATBOT_DIR . 'includes/class-org-chatbot-admin.php';

register_activation_hook( __FILE__, array( 'Org_Chatbot_Log', 'activate' ) );
register_deactivation_hook( __FILE__, array( 'Org_Chatbot_Log', 'deactivate' ) );

// Boot on init (priority 0), not plugins_loaded: settings defaults are translated,
// and WordPress 6.7+ warns when translations load before init.
add_action(
	'init',
	static function () {
		Org_Chatbot_Settings::init();
		Org_Chatbot_Log::init();
		Org_Chatbot_Faq::init();
		Org_Chatbot_Knowledge_Base::init();
		Org_Chatbot_Rest::init();
		Org_Chatbot_Widget::init();
		if ( is_admin() ) {
			Org_Chatbot_Admin::init();
		}
	},
	0
);
