import { Suspense } from "react";
import Header from "@/app/components/Header";
import DetailsDashboard from "./DetailsDashboard";

export default function DetailsPage() {
  return (
    <>
      <Header />
      <main className="flex-1">
        <Suspense fallback={
          <div className="flex items-center justify-center py-12 text-muted text-sm">Loading...</div>
        }>
          <DetailsDashboard />
        </Suspense>
      </main>
    </>
  );
}
