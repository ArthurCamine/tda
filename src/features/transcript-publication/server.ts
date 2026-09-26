import "server-only";
import { authConfig } from "@/features/auth/config";
import { getVerifiedServerIdentity } from "@/features/auth/server";
import { deniedPublicationDependencies } from "./consumer";
import { createPublicationHandler } from "./http";
import { databasePublicationDependencies } from "./repository";

const publication =
	process.env.TDA_TRANSCRIPT_PUBLICATION_ENABLED === "true"
		? databasePublicationDependencies
		: deniedPublicationDependencies;

const dependencies = {
	origin: () => authConfig()?.origin ?? null,
	identity: getVerifiedServerIdentity,
	publication,
};

export const publicationPost = createPublicationHandler(dependencies);
export const publicationReceiptPost = createPublicationHandler(
	dependencies,
	true,
);

import { createCurrentPublicationHandler } from "./current";
import { readCurrentPublication } from "./repository";
export const publicationCurrentPost = createCurrentPublicationHandler({ ...dependencies, read: readCurrentPublication });
