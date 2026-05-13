"use client";

import { Suspense } from "react";
import CreateRoomScreen from "@/components/screens/CreateRoomScreen";

function CreateRoomContent() {
  return <CreateRoomScreen />;
}

export default function CreateRoom() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-screen">Loading...</div>}>
      <CreateRoomContent />
    </Suspense>
  );
}
