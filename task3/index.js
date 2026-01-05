/**
 * Simple Express app that exposes a low-stock alert endpoint.
 * Data is intentionally kept in-memory to keep things easy to reason about.
 *
 * Endpoint:
 *   GET /api/companies/:companyId/alerts/low-stock
 */

const express = require('express');
const app = express();

app.use(express.json());

/* ---------------- Config / business rules ---------------- */

const LOW_STOCK_BY_TYPE = {
  'fast-moving': 50,
  'normal': 20,
  'slow-moving': 5
};

const SALES_LOOKBACK_DAYS = 90;   // product must have sales in this window
const SALES_AVG_DAYS = 30;        // used for avg daily sales calc

/* ---------------- In-memory data ---------------- */

const suppliers = {
  1: { id: 1, name: 'Supplier Corp', email: 'orders@supplier.com' },
  2: { id: 2, name: 'Another Supplies', email: 'hello@another.com' }
};

const companies = {
  1: { id: 1, name: 'Acme Corp' }
};

const warehouses = {
  1: { id: 1, companyId: 1, name: 'Main Warehouse' },
  2: { id: 2, companyId: 1, name: 'Overflow Warehouse' }
};

const products = {
  1: { id: 1, name: 'Widget A', sku: 'WID-001', productType: 'normal', supplierId: 1 },
  2: { id: 2, name: 'Gizmo B', sku: 'GIZ-002', productType: 'fast-moving', supplierId: 2 }
};

const inventories = [
  { id: 1, productId: 1, warehouseId: 1, quantity: 5 },
  { id: 2, productId: 1, warehouseId: 2, quantity: 0 },
  { id: 3, productId: 2, warehouseId: 1, quantity: 200 },
  { id: 4, productId: 2, warehouseId: 2, quantity: 10 }
];

// sales history
const now = new Date();
const daysAgo = (d) => new Date(now.getTime() - d * 24 * 60 * 60 * 1000);

const sales = [
  { id: 1, productId: 1, quantity: 10, createdAt: daysAgo(5) },
  { id: 2, productId: 2, quantity: 100, createdAt: daysAgo(200) },
  { id: 3, productId: 2, quantity: 60, createdAt: daysAgo(10) }
];

/* ---------------- Helper functions ---------------- */

function lowStockThreshold(product) {
  return LOW_STOCK_BY_TYPE[product.productType] || 10;
}

function salesSince(productId, cutoffDate) {
  return sales.filter(s =>
    s.productId === productId && s.createdAt >= cutoffDate
  );
}

function totalQuantity(items) {
  return items.reduce((sum, item) => sum + item.quantity, 0);
}

/* ---------------- Endpoint ---------------- */

app.get('/api/companies/:companyId/alerts/low-stock', (req, res) => {
  const companyId = Number(req.params.companyId);
  const company = companies[companyId];

  if (!company) {
    return res.status(404).json({ error: 'Company not found' });
  }

  const lookbackDate = daysAgo(SALES_LOOKBACK_DAYS);
  const avgWindowDate = daysAgo(SALES_AVG_DAYS);

  // get warehouses owned by this company
  const companyWarehouseIds = Object.values(warehouses)
    .filter(w => w.companyId === companyId)
    .map(w => w.id);

  const alerts = [];

  // group inventories by product
  const inventoriesByProduct = {};
  for (const inv of inventories) {
    if (!companyWarehouseIds.includes(inv.warehouseId)) continue;

    if (!inventoriesByProduct[inv.productId]) {
      inventoriesByProduct[inv.productId] = [];
    }
    inventoriesByProduct[inv.productId].push(inv);
  }

  for (const productId in inventoriesByProduct) {
    const product = products[productId];
    if (!product) continue;

    // only alert if there was recent activity
    const recentSales = salesSince(product.id, lookbackDate);
    if (recentSales.length === 0) continue;

    const avgSalesWindow = salesSince(product.id, avgWindowDate);
    const avgDailySales =
      SALES_AVG_DAYS > 0
        ? totalQuantity(avgSalesWindow) / SALES_AVG_DAYS
        : 0;

    const threshold = lowStockThreshold(product);

    for (const inv of inventoriesByProduct[productId]) {
      if (inv.quantity >= threshold) continue;

      let daysUntilStockout = null;
      if (avgDailySales > 0) {
        daysUntilStockout = Math.floor(inv.quantity / avgDailySales);
      }

      const supplier = suppliers[product.supplierId];

      alerts.push({
        product_id: product.id,
        product_name: product.name,
        sku: product.sku,
        warehouse_id: inv.warehouseId,
        warehouse_name: warehouses[inv.warehouseId]?.name || null,
        current_stock: inv.quantity,
        threshold: threshold,
        days_until_stockout: daysUntilStockout,
        supplier: supplier
          ? { id: supplier.id, name: supplier.name, contact_email: supplier.email }
          : null
      });
    }
  }

  res.json({
    alerts,
    total_alerts: alerts.length
  });
});

/* ---------------- Server ---------------- */

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
