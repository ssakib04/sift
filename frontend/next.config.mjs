/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  transpilePackages: ["@interviewflowai/talking-avatar"],
};

export default nextConfig;
