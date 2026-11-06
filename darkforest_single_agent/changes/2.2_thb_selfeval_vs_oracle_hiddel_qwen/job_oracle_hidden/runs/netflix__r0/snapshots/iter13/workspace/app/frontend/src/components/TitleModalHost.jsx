import { useEffect, useState } from 'react'
import { onOpenTitle } from '../lib/modalStore'
import TitleModal from './TitleModal'

export default function TitleModalHost() {
  const [openId, setOpenId] = useState(null)
  useEffect(() => onOpenTitle((id) => setOpenId(id)), [])
  if (openId == null) return null
  return <TitleModal titleId={openId} onClose={() => setOpenId(null)} />
}
