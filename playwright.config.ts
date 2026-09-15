import { defineConfig } from "@playwright/test";
export default defineConfig({
	testDir: "tests",
	testIgnore: ["statistics/**", "**/processing/**", "**/processing-integration/**"],
	workers: 2,
	use: { baseURL: "http://127.0.0.1:3101" },
	webServer: [
		{
			command: "pnpm start --port 3101",
			url: "http://127.0.0.1:3101/api/health",
			reuseExistingServer: false,
			env: {
				TDA_READ_PUBLISHED_DATA: "false",
				TDA_EDIT_UNSAFE: "true",
				TDA_WORLD_DEMO_FALLBACK: "true",
				TDA_E2E_FIXTURES: "true",
				SUPABASE_PUBLISHABLE_KEY: "",
				TDA_AUTH_ORIGIN: "",
			},
			timeout: 60000,
		},
		{
			command: "node tools/auth-browser-fixture.mjs",
			url: "http://127.0.0.1:3104/auth/v1/settings",
			reuseExistingServer: false,
		},
		{
			command: "pnpm start --port 3103",
			url: "http://127.0.0.1:3103/api/health",
			reuseExistingServer: false,
			env: {
				SUPABASE_URL: "http://127.0.0.1:3104",
				SUPABASE_PUBLISHABLE_KEY: "sb_publishable_synthetic",
				TDA_AUTH_ORIGIN: "http://127.0.0.1:3103",
				TDA_READ_EDIT_DATA: "false",
				TDA_EDIT_UNSAFE: "false",
				TDA_READ_PUBLISHED_DATA: "false",
				TDA_WORLD_DEMO_FALLBACK: "true",
			},
		},
	],
	projects: [
		{ name: "desktop-1080p", use: { viewport: { width: 1920, height: 1080 } } },
		{ name: "desktop-2k", use: { viewport: { width: 2560, height: 1440 } } },
		{ name: "mobile", use: { viewport: { width: 390, height: 844 } } },
	],
});
