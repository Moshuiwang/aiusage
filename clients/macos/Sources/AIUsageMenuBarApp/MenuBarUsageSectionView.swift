import AIUsageMenuBarCore
import SwiftUI

/// #177：用量区——标题弹出按钮（期间菜单）+ 总量 + 按 Agent 堆叠的趋势柱状图。
struct MenuBarUsageSectionView: View {
    @ObservedObject var model: MenuBarAppModel
    @Binding var periodMenuOpen: Bool
    @Environment(\.colorScheme) private var colorScheme

    @State private var menuMode: String = "week"
    @State private var showDatePicker = false
    @State private var pickedDate = Date()
    // #177 Opus 审查：periodMenuRows 会读盘（内存/磁盘缓存），不能放在 body 里当计算属性用——
    // 改成只在 selection 变化时算一次的缓存，菜单列表只在打开菜单时才计算。
    // 性能第二步：hoveredBar/hoverLocation 已下沉到 MenuBarTrendChartView 自己持有，
    // 本视图不再持有也不再传递这两个 Binding。
    @State private var cachedCurrentRow: PeriodMenuRow?
    @State private var cachedMenuRows: [PeriodMenuRow] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Button {
                    menuMode = model.selectedPeriodID
                    showDatePicker = false
                    cachedMenuRows = model.periodMenuRows(for: menuMode)
                    periodMenuOpen = true
                } label: {
                    HStack(spacing: 6) {
                        Text(cachedCurrentRow?.title ?? model.state.periodLabel)
                            .font(.system(size: 14, weight: .semibold))
                        Image(systemName: "chevron.up.chevron.down")
                            .font(.system(size: 9, weight: .bold))
                    }
                    .padding(.leading, 12)
                    .padding(.trailing, 10)
                    .padding(.vertical, 5)
                }
                .buttonStyle(.plain)
                .focusable(false)
                .background(
                    Capsule()
                        .fill(Color(nsColor: .controlBackgroundColor).opacity(periodMenuOpen ? 0.95 : 0.55))
                        .overlay(Capsule().stroke(Color.primary.opacity(0.10), lineWidth: 0.5))
                )
                .popover(isPresented: $periodMenuOpen, arrowEdge: .bottom) {
                    periodMenuPopoverContent
                }
                Text(cachedCurrentRow?.subtitle ?? model.state.dateRangeText)
                    .font(.system(size: 11))
                    .foregroundStyle(Color(nsColor: .secondaryLabelColor))
                Spacer(minLength: 0)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(model.state.heroTotalText)
                    .font(.system(size: 36, weight: .bold, design: .rounded))
                    .tracking(-1)
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                Text(model.state.tokenBreakdownText)
                    .font(.system(size: 11))
                    .foregroundStyle(Color(nsColor: .secondaryLabelColor))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }

            MenuBarTrendChartView(
                bars: model.state.trendBars,
                legendTotals: model.state.trendLegendTotals,
                ceilingFraction: model.state.trendCeilingFraction,
                ceilingText: model.state.trendRefCeilingText
            )
        }
        .padding(12)
        .background(cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.primary.opacity(0.07), lineWidth: 0.5)
        )
        .onAppear { refreshCurrentRowCache() }
        .onChange(of: model.selectedPeriodID) { _, _ in refreshCurrentRowCache() }
        .onChange(of: model.selectedOffset) { _, _ in refreshCurrentRowCache() }
        // 跨天后同一 selection 的标题/日期会变，随 summary 更新重算。
        .onChange(of: model.state.dateRangeText) { _, _ in refreshCurrentRowCache() }
    }

    private func refreshCurrentRowCache() {
        cachedCurrentRow = model.periodMenuRows(for: model.selectedPeriodID).first { $0.isSelected }
    }

    // MARK: – Period menu popover (原生 .popover：独立窗口，点外部/Esc 自动关闭，不被兄弟视图截断)

    @ViewBuilder
    private var periodMenuPopoverContent: some View {
        if showDatePicker {
            datePickerContent
        } else {
            periodMenuListContent
        }
    }

    private var periodMenuListContent: some View {
        VStack(spacing: 4) {
            segmentedModePicker
            ForEach(cachedMenuRows) { row in
                periodMenuRow(row)
            }
            Divider().padding(.horizontal, 6)
            Button {
                pickedDate = Date()
                showDatePicker = true
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "calendar")
                        .font(.system(size: 12))
                    Text("选择其他日期…")
                        .font(.system(size: 13))
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 7)
            }
            .buttonStyle(.plain)
            .focusable(false)
        }
        .padding(8)
        .frame(width: 300)
    }

    private var segmentedModePicker: some View {
        HStack(spacing: 2) {
            ForEach(MenuPeriodSelection.periodIDs, id: \.self) { id in
                let isSelected = menuMode == id
                Button {
                    menuMode = id
                    cachedMenuRows = model.periodMenuRows(for: menuMode)
                } label: {
                    Text(segmentLabel(id))
                        .font(.system(size: 12, weight: isSelected ? .semibold : .regular))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 4)
                }
                .buttonStyle(.plain)
                .focusable(false)
                .background(
                    Capsule()
                        .fill(isSelected ? Color(nsColor: .controlBackgroundColor) : Color.clear)
                        .shadow(color: .black.opacity(isSelected ? 0.10 : 0), radius: 2, x: 0, y: 1)
                )
            }
        }
        .padding(3)
        .background(Capsule().fill(Color.primary.opacity(0.06)))
        .padding(.bottom, 4)
    }

    private func segmentLabel(_ id: String) -> String {
        switch id {
        case "today": return "日"
        case "week": return "周"
        case "month": return "月"
        default: return id
        }
    }

    // #177 Opus 审查：#0A5CC2 字面量在深色/增强对比度下对比度不足，深色改用系统语义色
    // （Color.accentColor，随外观自动可读）；浅色仍保留设计稿的固定蓝。
    private var selectedRowTextColor: Color {
        colorScheme == .dark ? Color.accentColor : Color(red: 0.039, green: 0.361, blue: 0.761)
    }

    private var selectedRowBackgroundColor: Color {
        colorScheme == .dark
            ? Color.accentColor.opacity(0.24)
            : Color(red: 0.039, green: 0.518, blue: 1.0).opacity(0.12)
    }

    private var selectedRowSubtitleColor: Color {
        colorScheme == .dark ? Color.accentColor.opacity(0.85) : Color(red: 0.227, green: 0.471, blue: 0.788)
    }

    private func periodMenuRow(_ row: PeriodMenuRow) -> some View {
        Button {
            model.refresh(periodID: row.selection.periodID, offset: row.selection.offset)
            periodMenuOpen = false
        } label: {
            HStack(spacing: 8) {
                ZStack {
                    if row.isSelected {
                        Image(systemName: "checkmark")
                            .font(.system(size: 10, weight: .bold))
                    }
                }
                .frame(width: 14)
                VStack(alignment: .leading, spacing: 1) {
                    Text(row.title).font(.system(size: 13, weight: .medium))
                    Text(row.subtitle)
                        .font(.system(size: 10.5))
                        .foregroundStyle(row.isSelected ? selectedRowSubtitleColor : Color(nsColor: .secondaryLabelColor))
                }
                Spacer(minLength: 6)
                MenuBarMiniStackedBar(segments: row.segments)
                    .frame(width: 64, height: 6)
                Text(row.totalText)
                    .font(.system(size: 12, weight: .semibold).monospacedDigit())
                    .frame(width: 50, alignment: .trailing)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(row.isSelected ? selectedRowBackgroundColor : Color.clear)
            )
            .foregroundStyle(row.isSelected ? selectedRowTextColor : Color.primary)
        }
        .buttonStyle(.plain)
        .focusable(false)
    }

    // MARK: – 「选择其他日期…」内嵌在同一个 popover 里切换显示，不用 .sheet
    // （transient NSPopover 弹出 .sheet 在系统层面不可靠：sheet 依附的窗口可能随 popover
    // 一起被判定为失去焦点而提前关闭）。

    private var datePickerContent: some View {
        VStack(spacing: 12) {
            HStack {
                Button {
                    showDatePicker = false
                } label: {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 12, weight: .semibold))
                }
                .accessibilityLabel("返回")
                .buttonStyle(.plain)
                .focusable(false)
                Text("选择其他日期").font(.system(size: 13, weight: .semibold))
                Spacer()
            }
            DatePicker("", selection: $pickedDate, in: datePickerRange, displayedComponents: [.date])
                .datePickerStyle(.graphical)
                .labelsHidden()
            HStack {
                Button("取消") { showDatePicker = false }
                Spacer()
                Button("确定") {
                    let offset = PeriodMenuBuilder.offsetForPickedDate(
                        pickedDate,
                        periodID: menuMode,
                        now: Date(),
                        timezone: model.summary.timezone ?? model.todaySummary?.timezone
                    )
                    model.refresh(periodID: menuMode, offset: offset)
                    showDatePicker = false
                    periodMenuOpen = false
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(12)
        .frame(width: 300)
    }

    /// #177 Opus 审查：日粒度限选最近 7 天（今天...今天-6），与 MenuPeriodSelection 的
    /// offset 下限一致；周/月粒度上限为今天（不能选未来）。
    private var datePickerRange: ClosedRange<Date> {
        let calendar = Calendar.current
        let today = calendar.startOfDay(for: Date())
        switch menuMode {
        case "today":
            let earliest = calendar.date(byAdding: .day, value: -6, to: today) ?? today
            return earliest...today
        default:
            let earliest = calendar.date(byAdding: .year, value: -5, to: today) ?? today
            return earliest...today
        }
    }

    private var cardBackground: some ShapeStyle {
        Color(nsColor: .windowBackgroundColor).opacity(0.55)
    }
}

/// #177：期间菜单每行的迷你堆叠条，按 Agent 分段（复用 trendLegendTotals/segments 同款配色）。
struct MenuBarMiniStackedBar: View {
    let segments: [MenuTrendSegment]

    var body: some View {
        GeometryReader { geo in
            HStack(spacing: 0) {
                if segments.isEmpty {
                    Rectangle().fill(Color.primary.opacity(0.08))
                } else {
                    ForEach(segments) { segment in
                        Rectangle()
                            .fill(color(segment.provider))
                            .frame(width: geo.size.width * CGFloat(segment.fraction))
                    }
                }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
        .background(RoundedRectangle(cornerRadius: 3, style: .continuous).fill(Color.primary.opacity(0.08)))
    }

    private func color(_ provider: MenuTrendProvider) -> Color {
        let c = provider.color
        return Color(red: c.red, green: c.green, blue: c.blue, opacity: c.opacity)
    }
}
