import { createHash } from "node:crypto";
import { PutObjectCommand, S3Client } from "@aws-sdk/client-s3";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PUBLIC_BUCKET = "tda-media-public";
const PUBLIC_ORIGIN = "https://media.dnd.faysk.dev";

const assets = {
	"backgroud_jornada.avif": {
		bytes: 44678,
		sha256: "04ae4968021a938e8a8e738bbe84fea20f8e0900bba0be2b6cba70bc635e06b5",
		type: "image/avif",
	},
	"despedida_pais_background.avif": {
		bytes: 43481,
		sha256: "f096873034fe4cd14c1cfd24849dcf2fa127bcd65964dc9dd244846a7487421e",
		type: "image/avif",
	},
	"despedida_pais_destaque.avif": {
		bytes: 46697,
		sha256: "025d9245cb769525756e7fc9511257d22617905524c4c1c6764dce4fc4cbed86",
		type: "image/avif",
	},
	"despedida_tios_backgroud.avif": {
		bytes: 42002,
		sha256: "6e094723afb19b7be52115ecccfc291d699ead15e66bdea688befef07638c803",
		type: "image/avif",
	},
	"despedida_tios_destaque-personagem.avif": {
		bytes: 33161,
		sha256: "b065a145edf1f07651a49624bbd3be0740e0e167557a23fcba3a47990460f2bc",
		type: "image/avif",
	},
	"jornada.avif": {
		bytes: 52590,
		sha256: "e14ea119456bdd8688d96c6d9f854f90493480f6bedc6a1d1f871610904b3575",
		type: "image/avif",
	},
	"maos_sobre_mapa_matilha.avif": {
		bytes: 16734,
		sha256: "585df10d13dfbb442d9a12daafe22b1589c99c4397fd560f2b7911e8e3a3d4de",
		type: "image/avif",
	},
	"mapa_matilha_sem_mao.avif": {
		bytes: 84082,
		sha256: "84e87577d93d06b69e9b5d9ff644e2d860cae32ee4542b8e0a7c523124c6850c",
		type: "image/avif",
	},
	"sonho-paralax_personagem.avif": {
		bytes: 20734,
		sha256: "0a6d758ad05a37b84040e7548dbf693612fd55c4272f1f0a018a902213e1cca2",
		type: "image/avif",
	},
	"sonho_paralax_backgroud.avif": {
		bytes: 16786,
		sha256: "bcf5985f7f43bb50e40d36fc40a6e35192343cf39d9159a479ad0a62f3bab655",
		type: "image/avif",
	},
	"sonho_paralax_espirito.avif": {
		bytes: 13665,
		sha256: "650c460bad660ecb35184f1208771ec8659103735bdd797d1a7583369d7756da",
		type: "image/avif",
	},
	"sonho_paralax_nevoa.avif": {
		bytes: 14532,
		sha256: "dcfd8cfb7c1ab21a47a4441e34497935de06865140e0f79a56a9c0d63ea5cbb2",
		type: "image/avif",
	},
	"yllith.avif": {
		bytes: 73407,
		sha256: "d8d2f723883922f2b31682d946e4278bbe178c7ad769b69cf08cd2ed4eaca288",
		type: "image/avif",
	},
	"yllith_jornada.avif": {
		bytes: 33469,
		sha256: "92b5a5922c776170d251afa3190e33e62aab1fb6e1cd9465df437129608a8cad",
		type: "image/avif",
	},
	"social-yllith.jpg": {
		bytes: 225462,
		sha256: "c06d0be79fef0ef58d710f0243567724ed457610cbe657845e8297f41377cac9",
		type: "image/jpeg",
	},
} as const;

type AssetName = keyof typeof assets;

function isConfigured() {
	return Boolean(
		process.env.R2_PUBLIC_BUCKET === PUBLIC_BUCKET &&
			process.env.R2_ACCOUNT_ID &&
			process.env.R2_ACCESS_KEY_ID &&
			process.env.R2_SECRET_ACCESS_KEY,
	);
}

function publicUrl(name: AssetName) {
	const asset = assets[name];
	return `${PUBLIC_ORIGIN}/lore/yllith/${asset.sha256}/${name}`;
}

export async function GET() {
	return Response.json({
		environment: process.env.APP_ENV ?? null,
		configured: isConfigured(),
		assets: Object.keys(assets).map((name) => ({
			name,
			url: publicUrl(name as AssetName),
		})),
	});
}

export async function POST(request: Request) {
	if (process.env.APP_ENV !== "preview") {
		return Response.json({ error: "preview-only endpoint" }, { status: 404 });
	}
	if (!isConfigured()) {
		return Response.json({ error: "R2 configuration unavailable" }, { status: 503 });
	}

	const name = new URL(request.url).searchParams.get("file") as AssetName | null;
	if (!name || !(name in assets)) {
		return Response.json({ error: "unknown asset" }, { status: 400 });
	}

	const asset = assets[name];
	const bytes = Buffer.from(await request.arrayBuffer());
	if (bytes.length !== asset.bytes) {
		return Response.json({ error: "byte length mismatch" }, { status: 422 });
	}

	const digest = createHash("sha256").update(bytes).digest("hex");
	if (digest !== asset.sha256) {
		return Response.json({ error: "sha256 mismatch" }, { status: 422 });
	}

	const client = new S3Client({
		region: "auto",
		endpoint: `https://${process.env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
		credentials: {
			accessKeyId: process.env.R2_ACCESS_KEY_ID!,
			secretAccessKey: process.env.R2_SECRET_ACCESS_KEY!,
		},
		requestChecksumCalculation: "WHEN_REQUIRED",
	});

	const key = `lore/yllith/${asset.sha256}/${name}`;
	await client.send(
		new PutObjectCommand({
			Bucket: PUBLIC_BUCKET,
			Key: key,
			Body: bytes,
			ContentType: asset.type,
			CacheControl: "public, max-age=31536000, immutable",
		}),
	);

	return Response.json({
		ok: true,
		name,
		sha256: digest,
		bytes: bytes.length,
		key,
		url: publicUrl(name),
	});
}
