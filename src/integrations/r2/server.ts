import "server-only";
import { S3Client } from "@aws-sdk/client-s3";

export type MediaConnectionConfig = Readonly<{
	accountId: string;
	accessKeyId: string;
	secretAccessKey: string;
}>;

export function mediaConnectionConfig(): MediaConnectionConfig {
	const accountId = process.env.R2_ACCOUNT_ID;
	const accessKeyId = process.env.R2_ACCESS_KEY_ID;
	const secretAccessKey = process.env.R2_SECRET_ACCESS_KEY;
	if (!accountId || !accessKeyId || !secretAccessKey) {
		throw new Error("Media connection is not configured");
	}
	if (!/^[a-f0-9]{32}$/u.test(accountId)) throw new Error("Invalid media account");
	return { accountId, accessKeyId, secretAccessKey };
}

export function mediaClient() {
	const { accountId, accessKeyId, secretAccessKey } = mediaConnectionConfig();
	return new S3Client({
		region: "auto",
		endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
		credentials: { accessKeyId, secretAccessKey },
	});
}
