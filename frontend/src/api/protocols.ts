import { apiGet, apiPost } from './client'

export interface ProtocolInfo {
  id: string
  name: string
  description: string
}

export interface DecodedResult {
  success: boolean
  protocol_id: string
  protocol_name: string
  decoded: Record<string, any>
  message?: string
}

export async function listProtocols(): Promise<{ decoders: ProtocolInfo[] }> {
  return apiGet<{ decoders: ProtocolInfo[] }>('/api/protocols/')
}

export async function decodeData(rawHex: string, protocolId: string = 'auto'): Promise<DecodedResult> {
  return apiPost<DecodedResult>('/api/protocols/decode', {
    raw_hex: rawHex,
    protocol_id: protocolId,
  })
}

export async function encodeData(protocolId: string, data: Record<string, any>): Promise<{ raw_hex: string; length: number }> {
  return apiPost('/api/protocols/encode', {
    protocol_id: protocolId,
    data,
  })
}
