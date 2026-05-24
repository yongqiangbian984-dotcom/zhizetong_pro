var config = require('../../config.js');

Page({
  data: {
    reportHtml: '',
    loading: true,
    error: '',
    generating: false,
    mode: 'chat', // chat=旧版, full=6维完整报告
    // 6维报告数据
    reportData: null,
    dimKeys: [
      { key: 'step1_personality', icon: '🧠', title: '性格特质', index: '一' },
      { key: 'step2_fri', icon: '💰', title: '家庭资源', index: '二' },
      { key: 'step3_kondratiev', icon: '📈', title: '行业周期', index: '三' },
      { key: 'step4_location', icon: '🏙️', title: '地域价值', index: '四' },
      { key: 'step5_competition', icon: '🎓', title: '升学竞争', index: '五' },
      { key: 'step6_contingency', icon: '🎯', title: '容错规划', index: '六' }
    ]
  },

  onLoad: function(options) {
    var sysInfo = wx.getSystemInfoSync();
    this.setData({ statusBarHeight: sysInfo.statusBarHeight || 44 });

    var mode = (options && options.mode === 'full') ? 'full' : 'chat';
    this.setData({ mode: mode });

    if (mode === 'full') {
      this.loadFullReport();
    } else {
      this.loadReport();
    }
  },

  // ========== 6维完整报告 ==========
  loadFullReport: function() {
    var that = this;
    // 从缓存读取报告数据
    var reportData = null;
    try { reportData = wx.getStorageSync('zexiao_report_data'); } catch(e) {}

    if (reportData) {
      that.setData({ reportData: reportData, loading: false });
      return;
    }

    // 没有缓存，重新生成
    var profile = null;
    try { profile = wx.getStorageSync('zexiao_profile'); } catch(e) {}

    if (!profile || !profile.province || !profile.score) {
      that.setData({ loading: false, error: '缺少用户信息，请重新填写' });
      return;
    }

    that.setData({ generating: true });
    wx.showLoading({ title: '6维引擎生成中…', mask: true });

    var apiBase = config.zexiaoApiBase || 'http://localhost:8080';
    wx.request({
      url: apiBase + '/api/v1/consult',
      method: 'POST',
      header: { 'content-type': 'application/json' },
      data: {
        profile: {
          province: profile.province || '',
          score: profile.score || 0,
          subject: profile.subject || '理科',
          target_major: profile.target_major || '',
          target_university: profile.target_university || '',
          family_budget: profile.family_budget || '',
          personality: profile.personality || '',
          career_goal: profile.career_goal || '产业就业'
        }
      },
      timeout: 120000,
      success: function(res) {
        wx.hideLoading();
        if (res.statusCode === 200 && res.data && res.data.status === 'success') {
          that.setData({ reportData: res.data.data, loading: false, generating: false });
          try { wx.setStorageSync('zexiao_report_data', res.data.data); } catch(e) {}
        } else {
          var errMsg = '生成失败';
          if (res.data && res.data.message) errMsg = res.data.message;
          that.setData({ loading: false, error: errMsg, generating: false });
        }
      },
      fail: function() {
        wx.hideLoading();
        that.setData({ loading: false, error: '网络请求失败，请检查后端是否运行', generating: false });
      }
    });
  },

  // ========== 旧版聊天报告 ==========
  loadReport: function() {
    var that = this;
    that.setData({ loading: true, error: '', generating: false, reportHtml: '' });
    wx.showLoading({ title: '专业AI生成中…', mask: true });

    wx.cloud.callFunction({
      name: 'api',
      data: {
        action: 'zexiao_report',
        data: { preview: false }
      },
      timeout: 60000,
      success: function(res) {
        wx.hideLoading();
        if (res.result && res.result.code === 0) {
          var content = res.result.data.report.content || '';
          if (content) {
            var html = that.mdToHtml(content);
            that.setData({ reportHtml: html, loading: false });
          } else {
            that.setData({ loading: false, error: '报告内容为空' });
          }
        } else if (res.result && res.result.code === 402) {
          that.loadPreview();
        } else if (res.result && res.result.code === 403) {
          that.setData({ loading: false, error: '信息收集尚未完成，请先完成对话评估' });
        } else {
          that.setData({ loading: false, error: (res.result && res.result.message) || '生成失败' });
        }
      },
      fail: function() {
        wx.hideLoading();
        that.setData({ loading: false, error: '网络异常，请重试' });
      }
    });
  },

  loadPreview: function() {
    var that = this;
    wx.showLoading({ title: '专业AI生成中…', mask: true });
    wx.cloud.callFunction({
      name: 'api',
      data: {
        action: 'zexiao_report',
        data: { preview: true }
      },
      timeout: 60000,
      success: function(res) {
        wx.hideLoading();
        if (res.result && res.result.code === 0) {
          var content = res.result.data.report.content || '';
          if (content) {
            var html = that.mdToHtml(content);
            that.setData({ reportHtml: html, loading: false });
          }
        } else {
          that.setData({ loading: false, error: '预览生成失败' });
        }
      },
      fail: function() {
        wx.hideLoading();
        that.setData({ loading: false, error: '网络异常' });
      }
    });
  },

  mdToHtml: function(md) {
    var html = md;
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/^---$/gm, '<hr/>');
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, function(m) { return '<ul>' + m + '</ul>'; });
    html = html.replace(/^(?!<[hluo]|<hr|<li|<strong|<em)(.+)$/gm, '<p>$1</p>');
    html = html.replace(/\n{2,}/g, '\n');
    return html;
  },

  goBack: function() {
    wx.navigateBack();
  },

  retryReport: function() {
    if (this.data.mode === 'full') {
      this.loadFullReport();
    } else {
      this.loadReport();
    }
  },

  // 获取6维某一项的值
  getDimValue: function(key, field) {
    var data = this.data.reportData;
    if (!data || !data[key]) return '-';
    return data[key][field] || '-';
  }
});
