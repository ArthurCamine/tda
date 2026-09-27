import type { ExecutionDevice, SystemGpu } from "./protocol";

/** Never use a CUDA ordinal to index physical telemetry; ambiguous joins stay unknown. */
export function selectExecutionGpu(rows: readonly SystemGpu[], device: ExecutionDevice | null | undefined): SystemGpu | null {
 if (device?.kind !== "cuda") return null;
 const matches = device.physicalUuid ? rows.filter(row => row.uuid === device.physicalUuid) : device.pciBusId ? rows.filter(row => row.pciBusId === device.pciBusId) : [];
 return matches.length === 1 ? matches[0] : null;
}

export function executionHardwareKey(device: ExecutionDevice | null | undefined): string | null {
 if (device?.kind !== "cuda") return null;
 return device.physicalUuid ?? (device.pciBusId ? `pci:${device.pciBusId}` : null);
}
