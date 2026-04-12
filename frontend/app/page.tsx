import Dashboard from "@/app/components/Dashboard";
import Header from "@/app/components/Header";

export default function Home() {
  return (
    <>
      <Header />
      <main className="flex-1">
        <Dashboard />
      </main>
    </>
  );
}
