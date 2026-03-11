import pandas as pd

# Función para computar MRP de un ítem
def compute_mrp(gross_req, initial_inv, lead_time, scheduled_receipts=None):
    if scheduled_receipts is None:
        scheduled_receipts = [0] * len(gross_req)
    
    projected_inv = [initial_inv]
    net_req = [0]
    planned_receipts = [0]
    planned_orders = [0] * lead_time + [0] * (len(gross_req) - lead_time)
    
    for t in range(len(gross_req)):
        proj = projected_inv[t] + scheduled_receipts[t] - gross_req[t]
        net = max(0, -proj)
        net_req.append(net)
        
        receipt = net  # Lot-for-lot
        planned_receipts.append(receipt)
        
        if t + lead_time < len(gross_req):
            planned_orders[t + lead_time] = receipt
        
        next_inv = projected_inv[t] + scheduled_receipts[t] + receipt - gross_req[t] if proj < 0 else projected_inv[t] + scheduled_receipts[t] - gross_req[t]
        projected_inv.append(next_inv)
    
    return {
        'Gross Requirements': gross_req,
        'Scheduled Receipts': scheduled_receipts,
        'Projected Inventory': projected_inv[1:],
        'Net Requirements': net_req[1:],
        'Planned Receipts': planned_receipts[1:],
        'Planned Order Releases': planned_orders[:len(gross_req)]
    }

# Datos de ejemplo
weeks = [1, 2, 3, 4, 5]
fg_gross = [10, 15, 20, 10, 5]  # Demanda de FG
fg_inventory = 5  # Inventario inicial
fg_lead = 1  # Lead time

# Computar para FG
fg_mrp = compute_mrp(fg_gross, fg_inventory, fg_lead)
fg_df = pd.DataFrame(fg_mrp, index=weeks)

# Gross para componentes (de planned receipts de FG * BOM qty)
part1_gross = [pr * 2 for pr in fg_mrp['Planned Receipts']]  # 2x Part1 por FG
part1_inv = 10
part1_lead = 2
part1_mrp = compute_mrp(part1_gross, part1_inv, part1_lead)
part1_df = pd.DataFrame(part1_mrp, index=weeks)

part2_gross = [pr * 3 for pr in fg_mrp['Planned Receipts']]  # 3x Part2 por FG
part2_inv = 15
part2_lead = 1
part2_mrp = compute_mrp(part2_gross, part2_inv, part2_lead)
part2_df = pd.DataFrame(part2_mrp, index=weeks)

# Mostrar resultados
print("MRP para Producto Terminado (FG):")
print(fg_df)
print("\nMRP para Part1:")
print(part1_df)
print("\nMRP para Part2:")
print(part2_df)