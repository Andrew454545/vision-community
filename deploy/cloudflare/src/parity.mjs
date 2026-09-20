import { seedBytes, renderFacesFromSeed, embeddingFor, sha256Hex } from "./model.js";

const [assetId, capture, lane] = process.argv.slice(2);
const faces = renderFacesFromSeed(await seedBytes(assetId, capture, lane, "community-visual-v1"));
const embedding = embeddingFor(lane, faces);
process.stdout.write(await sha256Hex(embedding));
