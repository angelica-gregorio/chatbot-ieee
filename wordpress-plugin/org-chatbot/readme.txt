=== Organization FAQ Chatbot ===
Contributors: cpecaps-team
Tags: faq, chatbot, accessibility, voice
Requires at least: 6.4
Requires PHP: 8.1
Stable tag: 0.2.0
License: GPL-2.0-or-later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

FAQ chatbot for the Organization website. Answers typed and spoken questions using only approved FAQ entries.

== Description ==

* A chat button on every public page (FR-21). Answers come only from published FAQ entries; when nothing matches, the bot gives the inquiry email and links for the closest concern instead of guessing (FR-22).
* Spoken questions: the visitor presses the microphone, agrees to the notice, and speaks. The recording is turned into text by an E-Branchformer speech model in the companion chatbot service, and is not stored.
* Administrators manage answers as FAQ entries: each entry has a "Chatbot" box to switch it off, add other ways people ask the question, and add related links (FR-23).
* Chatbot > Unanswered questions lists what the bot could not answer, with counts and dates, after masking names, emails, phone and ID numbers (FR-23).
* [org_faq] shortcode renders the FAQ page grouped by category.

Requires the chatbot service from the same repository (chatbot-service/), reachable over HTTPS.

== Installation ==

1. Copy the org-chatbot folder to wp-content/plugins/ and activate it.
2. In wp-config.php add: define( 'ORG_CHATBOT_SHARED_SECRET', '...' ); using the same value as WP_SHARED_SECRET in the service.
3. Chatbot > Settings: enter the service URL, the FAQ, Contact and Privacy Notice page URLs, and the inquiry emails for each concern.
4. Add FAQ entries under FAQs. Put [org_faq] on the FAQ page.
5. Allow the service in the site's Content-Security-Policy connect-src if one is set.

== Changelog ==

= 0.2.0 =
* New widget design: gradient header with site icon and site name, rounded message bubbles, orange send button, round launcher.
* Voice: recordings are resampled to 16 kHz with the browser's resampler, which gives the speech model clearer audio.

= 0.1.0 =
* First version for Release 2 planning.
