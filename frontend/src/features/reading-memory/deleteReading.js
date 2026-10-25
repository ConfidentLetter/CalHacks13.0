// A record's source describes where it originated, not where copies are stored.
export async function deleteReadingCopies(record, { remoteItems, extensionItems, deleteRemote, deleteLocal }) {
  const local = extensionItems.find((item) => String(item.id) === record.id)
  const remote = remoteItems.some((item) => item.id === record.id)
  if (remote || record.source !== 'extension' || (local || record).synced !== false) {
    await deleteRemote(record.id)
  }
  if (local || record.source === 'extension') await deleteLocal(record.id)
}
