import Header from "@/app/components/Header";
import SkierDashboard from "@/app/components/SkierDashboard";

export default function Home() {
  return (
    <>
      <Header />
      <main className="flex-1">
        <SkierDashboard />
      </main>
    </>
  );
}
