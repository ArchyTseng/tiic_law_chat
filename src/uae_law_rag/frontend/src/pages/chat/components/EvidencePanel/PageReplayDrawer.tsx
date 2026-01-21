import type { PageReplay as PageReplayRecord } from '@/types/domain/evidence'
import PageReplay from '@/pages/chat/components/EvidencePanel/PageReplay'
import { Drawer } from '@/ui/components'

type LoadStatus = 'idle' | 'loading' | 'failed' | 'loaded'

type PageReplayDrawerProps = {
  open: boolean
  status: LoadStatus
  replay?: PageReplayRecord
  onClose: () => void
}

const PageReplayDrawer = ({ open, status, replay, onClose }: PageReplayDrawerProps) => {
  return (
    <div className="page-replay-drawer">
      <Drawer open={open} title="Page Replay" onClose={onClose}>
        <PageReplay status={status} replay={replay} />
      </Drawer>
    </div>
  )
}

export default PageReplayDrawer
