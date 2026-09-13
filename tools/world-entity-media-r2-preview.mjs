import {
	GetBucketCorsCommand,
	GetBucketLifecycleConfigurationCommand,
	PutBucketCorsCommand,
	PutBucketLifecycleConfigurationCommand,
	S3Client,
} from "@aws-sdk/client-s3";
import {
	WORLD_ENTITY_MEDIA_PENDING_LIFECYCLE_RULE_ID,
	WORLD_ENTITY_MEDIA_PREVIEW_BUCKET,
	WORLD_ENTITY_MEDIA_PREVIEW_CORS_RULE_ID,
	replaceManagedRule,
	worldEntityMediaCorsRuleMatches,
	worldEntityMediaLifecycleRuleMatches,
	worldEntityMediaPendingLifecycleRule,
	worldEntityMediaPreviewCorsRule,
} from "./world-entity-media-r2-policy.mjs";

function parseArguments(argv) {
	let mode = "plan";
	let origin = null;
	let confirmPreview = false;
	for (let index = 0; index < argv.length; index += 1) {
		const argument = argv[index];
		if (argument === "--check") mode = "check";
		else if (argument === "--apply") mode = "apply";
		else if (argument === "--confirm-preview") confirmPreview = true;
		else if (argument === "--origin") {
			origin = argv[index + 1] ?? null;
			index += 1;
		} else {
			throw new Error(`Unknown argument: ${argument}`);
		}
	}
	if (!origin) throw new Error("Use --origin https://<deployment>.vercel.app");
	return { mode, origin, confirmPreview };
}

function missingConfiguration(error) {
	const status = error?.$metadata?.httpStatusCode;
	return (
		status === 404 ||
		error?.name === "NoSuchCORSConfiguration" ||
		error?.name === "NoSuchLifecycleConfiguration" ||
		error?.name === "NoSuchConfiguration"
	);
}

function r2ClientFromEnvironment() {
	const accountId = process.env.R2_ACCOUNT_ID;
	const accessKeyId = process.env.R2_ACCESS_KEY_ID;
	const secretAccessKey = process.env.R2_SECRET_ACCESS_KEY;
	if (!accountId || !/^[a-f0-9]{32}$/u.test(accountId)) {
		throw new Error("R2_ACCOUNT_ID is missing or invalid");
	}
	if (!accessKeyId || !secretAccessKey) {
		throw new Error("R2 preview configuration credentials are missing");
	}
	return new S3Client({
		region: "auto",
		endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
		credentials: { accessKeyId, secretAccessKey },
	});
}

async function currentCorsRules(client, bucket) {
	try {
		const response = await client.send(new GetBucketCorsCommand({ Bucket: bucket }));
		return response.CORSRules ?? [];
	} catch (error) {
		if (missingConfiguration(error)) return [];
		throw error;
	}
}

async function currentLifecycleRules(client, bucket) {
	try {
		const response = await client.send(
			new GetBucketLifecycleConfigurationCommand({ Bucket: bucket }),
		);
		return response.Rules ?? [];
	} catch (error) {
		if (missingConfiguration(error)) return [];
		throw error;
	}
}

function managedRule(rules, id) {
	return rules.find((rule) => rule?.ID === id);
}

function printPlan({ bucket, origin, corsRule, lifecycleRule }) {
	console.log(
		JSON.stringify(
			{
				bucket,
				origin,
				corsManagedRule: corsRule,
				lifecycleManagedRule: lifecycleRule,
				note: "Only these managed IDs are replaced; unrelated bucket rules are preserved.",
			},
			null,
			2,
		),
	);
}

const { mode, origin, confirmPreview } = parseArguments(process.argv.slice(2));
const bucket = process.env.R2_PREVIEW_BUCKET ?? WORLD_ENTITY_MEDIA_PREVIEW_BUCKET;
if (bucket !== WORLD_ENTITY_MEDIA_PREVIEW_BUCKET) {
	throw new Error(`Refusing non-preview bucket: ${bucket}`);
}
const corsRule = worldEntityMediaPreviewCorsRule(origin);
const lifecycleRule = worldEntityMediaPendingLifecycleRule();

if (mode === "plan") {
	printPlan({ bucket, origin: corsRule.AllowedOrigins[0], corsRule, lifecycleRule });
	process.exit(0);
}

const client = r2ClientFromEnvironment();
const [corsRules, lifecycleRules] = await Promise.all([
	currentCorsRules(client, bucket),
	currentLifecycleRules(client, bucket),
]);

if (mode === "check") {
	const corsOk = worldEntityMediaCorsRuleMatches(
		managedRule(corsRules, WORLD_ENTITY_MEDIA_PREVIEW_CORS_RULE_ID),
		corsRule,
	);
	const lifecycleOk = worldEntityMediaLifecycleRuleMatches(
		managedRule(lifecycleRules, WORLD_ENTITY_MEDIA_PENDING_LIFECYCLE_RULE_ID),
		lifecycleRule,
	);
	console.log(`R2_WORLD_MEDIA_PREVIEW_CORS=${corsOk ? "OK" : "MISMATCH"}`);
	console.log(`R2_WORLD_MEDIA_PENDING_LIFECYCLE=${lifecycleOk ? "OK" : "MISMATCH"}`);
	if (!corsOk || !lifecycleOk) process.exitCode = 2;
} else if (mode === "apply") {
	if (!confirmPreview) {
		throw new Error("Apply requires --confirm-preview");
	}
	const nextCorsRules = replaceManagedRule(corsRules, corsRule);
	const nextLifecycleRules = replaceManagedRule(lifecycleRules, lifecycleRule);
	await client.send(
		new PutBucketCorsCommand({
			Bucket: bucket,
			CORSConfiguration: { CORSRules: nextCorsRules },
		}),
	);
	await client.send(
		new PutBucketLifecycleConfigurationCommand({
			Bucket: bucket,
			LifecycleConfiguration: { Rules: nextLifecycleRules },
		}),
	);

	const [verifiedCors, verifiedLifecycle] = await Promise.all([
		currentCorsRules(client, bucket),
		currentLifecycleRules(client, bucket),
	]);
	const corsOk = worldEntityMediaCorsRuleMatches(
		managedRule(verifiedCors, WORLD_ENTITY_MEDIA_PREVIEW_CORS_RULE_ID),
		corsRule,
	);
	const lifecycleOk = worldEntityMediaLifecycleRuleMatches(
		managedRule(verifiedLifecycle, WORLD_ENTITY_MEDIA_PENDING_LIFECYCLE_RULE_ID),
		lifecycleRule,
	);
	if (!corsOk || !lifecycleOk) {
		throw new Error("R2 preview policy read-back verification failed");
	}
	console.log(`R2_WORLD_MEDIA_PREVIEW_POLICY_APPLIED bucket=${bucket}`);
} else {
	throw new Error(`Unsupported mode: ${mode}`);
}
