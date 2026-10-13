import js from '@eslint/js';
import globals from 'globals';

export default [
	js.configs.recommended,
	{
		files: [ 'wordpress-plugin/org-chatbot/assets/js/chat-widget.js' ],
		languageOptions: {
			ecmaVersion: 2022,
			sourceType: 'script',
			globals: { ...globals.browser },
		},
		rules: {
			'no-unused-vars': [ 'error', { caughtErrors: 'none' } ],
			eqeqeq: 'error',
			'no-var': 'error',
			'prefer-const': 'error',
		},
	},
	{
		files: [ 'wordpress-plugin/org-chatbot/assets/js/recorder-worklet.js' ],
		languageOptions: {
			ecmaVersion: 2022,
			sourceType: 'script',
			globals: { AudioWorkletProcessor: 'readonly', registerProcessor: 'readonly' },
		},
	},
];
