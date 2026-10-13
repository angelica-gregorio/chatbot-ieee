<?php
/**
 * Removes personal identifiers from logged questions (FR-23 AC2, NFR-CMP-01).
 *
 * The chatbot service already redacts before sending; this is applied again on
 * receipt so nothing identifying reaches the database even if the service is
 * misconfigured. Keep the patterns in step with chatbot-service/app/privacy.py.
 *
 * @package OrgChatbot
 */

defined( 'ABSPATH' ) || exit;

/**
 * Pattern-based redaction of emails, links, phone and ID numbers, names and secrets.
 */
class Org_Chatbot_Redactor {

	/**
	 * Mask identifiers in a question.
	 *
	 * @param string $text Question text.
	 * @return string
	 */
	public static function redact( $text ) {
		$text = (string) $text;
		$text = preg_replace( '/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/iu', '[email]', $text );
		$text = preg_replace( '#\bhttps?://\S+#i', '[link]', $text );
		$text = preg_replace(
			'/\b(password|passcode|pin|otp|tin|sss|philhealth|pag-?ibig|umid|passport|card number|cvv)\b(\s*(?:is|:|=|ko ay|ko)?\s*)(\S+)/i',
			'$1$2[redacted]',
			$text
		);
		$text = preg_replace( '/(?:\+?63|0)[\s.-]?9\d{2}[\s.-]?\d{3}[\s.-]?\d{4}\b/', '[phone]', $text );
		$text = preg_replace( '/\(?\b0?2\)?[\s.-]?\d{3,4}[\s.-]?\d{4}\b/', '[phone]', $text );
		$text = preg_replace( '/\b\d[\d\s-]{5,}\d\b/', '[number]', $text );
		$text = preg_replace(
			"/\\b((?i:my name is|my name's|i am|i'm|im|this is|ako si|ako po si|pangalan ko ay))\\s+((?:[A-Z][\\w'-]+)(?:\\s+(?:de|dela|del|delos|van|von|[A-Z][\\w'-]+)){0,3})/u",
			'$1 [name]',
			$text
		);
		return trim( preg_replace( '/\s+/u', ' ', $text ) );
	}
}
