import { ImageResponse } from 'next/og';

export const runtime = 'edge';

export const alt = 'SlotScan - Ethereum Storage Analyzer';
export const size = {
  width: 1200,
  height: 600,
};
export const contentType = 'image/png';

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: '#ffffff',
          fontFamily: 'monospace',
        }}
      >
        {/* Dashed border container */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '50px 70px',
            border: '3px dashed #000000',
            gap: '20px',
          }}
        >
          {/* Logo mark - 0x55 */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '0px',
            }}
          >
            <span
              style={{
                fontSize: '64px',
                fontWeight: 400,
                color: '#000000',
                letterSpacing: '2px',
                lineHeight: 1.1,
              }}
            >
              0x
            </span>
            <span
              style={{
                fontSize: '64px',
                fontWeight: 400,
                color: '#000000',
                letterSpacing: '2px',
                lineHeight: 1.1,
              }}
            >
              55
            </span>
          </div>

          {/* Brand name */}
          <span
            style={{
              fontSize: '42px',
              fontWeight: 400,
              color: '#000000',
              marginTop: '12px',
            }}
          >
            SlotScan
          </span>

          {/* Tagline */}
          <span
            style={{
              fontSize: '22px',
              color: '#666666',
            }}
          >
            Ethereum Storage Analyzer
          </span>
        </div>
      </div>
    ),
    {
      ...size,
    }
  );
}
