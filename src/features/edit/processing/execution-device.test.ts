import { expect, it } from "vitest";
import { selectExecutionGpu, executionHardwareKey } from "./execution-device";
import { parseExecutionDevice, type SystemGpu } from "./protocol";
const rows: SystemGpu[] = [
 { index: 0, uuid: "GPU-11111111-1111-1111-1111-111111111111", pciBusId: "00000000:01:00.0", name: "RTX 4070", utilizationPercent: 50, memoryUsedBytes: 1, memoryTotalBytes: 2 },
 { index: 1, uuid: "GPU-22222222-2222-2222-2222-222222222222", pciBusId: "00000000:02:00.0", name: "RTX 3090", utilizationPercent: 90, memoryUsedBytes: 1, memoryTotalBytes: 2 },
];
it("selects physical telemetry independently of logical ordinal and row order", () => {
 const device = parseExecutionDevice({ kind: "cuda", logical_index: 0, physical_uuid: rows[1].uuid, pci_bus_id: rows[1].pciBusId });
 expect(selectExecutionGpu(rows, device)?.name).toBe("RTX 3090");
 expect(selectExecutionGpu([...rows].reverse(), device)?.name).toBe("RTX 3090");
 const other = { ...device!, physicalUuid: rows[0].uuid! };
 expect(executionHardwareKey(device)).not.toBe(executionHardwareKey(other));
});
it("never infers physical identity from an ordinal, including legacy runs", () => {
 const device = parseExecutionDevice({ kind: "cuda", logical_index: 0 });
 expect(selectExecutionGpu(rows, device)).toBeNull(); expect(executionHardwareKey(device)).toBeNull();
 expect(selectExecutionGpu(rows, { ...device!, physicalUuid: "MIG-33333333-3333-3333-3333-333333333333", pciBusId: rows[0].pciBusId! })).toBeNull();
 expect(selectExecutionGpu([rows[0], rows[0]], { ...device!, pciBusId: rows[0].pciBusId! })).toBeNull();
 expect(parseExecutionDevice(undefined)).toBeNull();
});
