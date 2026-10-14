export function Atmosphere() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-night">
      <div className="absolute -left-40 -top-40 h-[40rem] w-[60rem] rounded-full bg-wine/80 blur-atmosphere" />
      <div className="absolute left-[18%] top-[30%] h-[30rem] w-[32rem] rounded-full bg-crimson/55 blur-atmosphere" />
      <div className="absolute -right-40 -top-56 h-[40rem] w-[48rem] rounded-full bg-rust blur-atmosphere" />
      <div className="absolute right-[6%] -top-16 h-[24rem] w-[30rem] rounded-full bg-amber/90 blur-atmosphere" />
      <div className="atmosphere-drift absolute right-[8%] top-[24%] h-[34rem] w-[34rem] rounded-full bg-ember/95 blur-atmosphere" />
      <div className="absolute right-[24%] top-[50%] h-[14rem] w-[14rem] rounded-full bg-peach/65 blur-atmosphere" />
      <div className="absolute -bottom-48 -right-32 h-[44rem] w-[44rem] rounded-full bg-crimson/85 blur-atmosphere" />
      <div className="absolute -bottom-40 left-[20%] h-[22rem] w-[36rem] rounded-full bg-rust/70 blur-atmosphere" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_62%_38%,transparent_40%,rgb(16_9_8/0.35)_75%,rgb(16_9_8/0.8)_100%)]" />
      <div className="absolute inset-y-0 left-0 w-[40rem] bg-gradient-to-r from-night/85 via-night/35 to-transparent" />
      <div className="atmosphere-grain absolute inset-0" />
    </div>
  );
}
