import React from "react";
import TanStackTable from "./ui/tanstack-table";

export default function Table({ columns, rows, max = 200, className = "" }) {
  if (!columns || !rows) return null;
  const slicedData = max ? rows.slice(0, max) : rows;

  return (
    <div className={className}>
      <TanStackTable
        columns={columns}
        data={slicedData}
        pageSize={15}
        enablePagination={slicedData.length > 15}
        enableGlobalFilter={slicedData.length > 5}
        enableColumnVisibility={columns.length > 5}
      />
    </div>
  );
}
