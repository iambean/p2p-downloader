/// Invalidates reads started before a mutation, preventing late snapshots from
/// restoring obsolete task status after pause/resume has finished.
public struct SnapshotGeneration {
    public private(set) var current: UInt64 = 0
    public init() {}
    public mutating func invalidate() { current &+= 1 }
    public func accepts(_ generation: UInt64) -> Bool { generation == current }
}
