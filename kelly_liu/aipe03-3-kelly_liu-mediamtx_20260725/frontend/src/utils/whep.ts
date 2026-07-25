export interface WhepSession {
  peerConnection: RTCPeerConnection;
  close: () => void;
}

function waitForIceGatheringComplete(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const onChange = () => {
      if (pc.iceGatheringState !== 'complete') return;
      pc.removeEventListener('icegatheringstatechange', onChange);
      resolve();
    };
    pc.addEventListener('icegatheringstatechange', onChange);
  });
}

export async function connectWhep(
  video: HTMLVideoElement,
  whepUrl: string,
  streamToken: string,
  onStateChange: (state: RTCPeerConnectionState) => void,
): Promise<WhepSession> {
  const pc = new RTCPeerConnection({ iceServers: [] });
  pc.addTransceiver('video', { direction: 'recvonly' });
  pc.onconnectionstatechange = () => onStateChange(pc.connectionState);
  pc.ontrack = (event) => {
    video.srcObject = event.streams[0] ?? new MediaStream([event.track]);
    void video.play();
  };

  try {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitForIceGatheringComplete(pc);

    const response = await fetch(whepUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/sdp',
        Authorization: `Bearer ${streamToken}`,
      },
      body: pc.localDescription?.sdp,
    });
    if (!response.ok) throw new Error(`MediaMTX 回傳 ${response.status}`);

    await pc.setRemoteDescription({ type: 'answer', sdp: await response.text() });
    return {
      peerConnection: pc,
      close: () => {
        pc.ontrack = null;
        pc.onconnectionstatechange = null;
        pc.close();
        video.srcObject = null;
      },
    };
  } catch (error) {
    pc.close();
    video.srcObject = null;
    throw error;
  }
}
