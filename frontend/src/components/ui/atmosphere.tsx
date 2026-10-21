export function Atmosphere() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-[#12090a]">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_86%_-6%,#c46234_0%,#8a3a26_18%,#4a1c16_40%,#241010_62%,#12090a_100%)]" />
      <div className="absolute -right-32 -top-48 h-[38rem] w-[46rem] rounded-full bg-[#c45a30]/28 blur-[120px]" />
      <div className="absolute right-[6%] top-[-2rem] h-[20rem] w-[28rem] rounded-full bg-[#4a1818]/70 blur-[100px]" />
      <div className="absolute right-[18%] top-[14%] h-[18rem] w-[32rem] rounded-full bg-[#1c0c0c]/90 blur-[110px]" />
      <div className="absolute right-[-6%] top-[28%] h-[16rem] w-[26rem] rounded-full bg-[#f0a04b]/38 blur-[100px]" />
      <div className="absolute right-[24%] top-[36%] h-[14rem] w-[24rem] rounded-full bg-[#6a2420]/70 blur-[110px]" />
      <div className="absolute right-[2%] top-[46%] h-[16rem] w-[22rem] rounded-full bg-[#c45a30]/28 blur-[100px]" />
      <div className="absolute bottom-[-14rem] left-[12%] h-[24rem] w-[46rem] rounded-full bg-[#c45a30]/40 blur-[120px]" />
      <div className="absolute bottom-[-8rem] right-[-4rem] h-[18rem] w-[30rem] rounded-full bg-[#e36a2e]/40 blur-[110px]" />
      <div className="absolute bottom-[8%] left-[36%] h-[12rem] w-[28rem] rounded-full bg-[#f0a04b]/24 blur-[90px]" />
      <div className="absolute inset-0 bg-[linear-gradient(102deg,#100808_0%,rgb(16_8_8/0.78)_24%,rgb(18_9_10/0.28)_46%,transparent_64%)]" />
      <div className="absolute right-0 top-0 h-[40rem] w-[46rem] bg-[radial-gradient(ellipse_at_100%_0%,rgb(12_6_6/0.48)_0%,rgb(42_18_14/0.22)_48%,transparent_76%)]" />
      <div className="atmosphere-grain absolute inset-0" />
    </div>
  );
}
