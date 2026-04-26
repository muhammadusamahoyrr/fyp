import './globals.css';

export const metadata = {
  title: 'AttorneyAI — Legal Intelligence Platform',
  description: 'AI-powered legal assistance for Pakistani citizens',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
