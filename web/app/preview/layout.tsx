import { AntdRegistry } from '@ant-design/nextjs-registry'

import { sans } from './fonts'

export default function PreviewLayout({ children }: { children: React.ReactNode }) {
  return (
    <AntdRegistry>
      {/* The existing root layout renders its own header and pads main on every
          route. Adopting antd for real replaces that layout outright; neutralising
          it here keeps the preview honest about what the screen will look like. */}
      <style>{`
        body > header { display: none !important; }
        body > main { padding: 0 !important; }
      `}</style>
      <div className={sans.className}>{children}</div>
    </AntdRegistry>
  )
}
