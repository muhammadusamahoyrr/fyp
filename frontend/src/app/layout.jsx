import './globals.css';
import Providers from './Providers';

export const metadata = {
  title: 'Attorney AI — Legal Intelligence Platform',
  description: 'AI-powered legal assistance for Pakistani citizens. Instant research, document automation, and lawyer matching — built for Pakistan.',
  icons: { icon: '/new_logo.ico' },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en-PK">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
