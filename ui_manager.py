# -*- coding:utf-8 -*-
"""
:keyword NUAA QianKe
哦 我的上帝啊
南航的工图为什么这么恶心

Fuck UI program
"""

from PySide6.QtWidgets import QApplication
from PySide6.QtUiTools import QUiLoader
from PySide6 import QtGui
from fuck_page import *

class Stats(object):

    def __init__(self):
        self.ui = QUiLoader().load('./snatcher.ui')
        self.ui.setWindowIcon(QtGui.QIcon("icon.ico"))
        self.whether_load = False
        self.pid = ""
        self.cookie = ""
        self.session = None

        # chose_list = [ID(str)]
        self.chose_list = []
        self.n = 0

        # data_
        self.id_list = []
        self.name_list = []
        self.teacher_list = []

        # mode
        self.used_p = ""


        self.ui.commandLinkButton.clicked.connect(self.go)
        self.ui.commandLinkButton_2.clicked.connect(self.load_base)
        self.ui.pushButton.clicked.connect(self.load_all)
        self.ui.pushButton_2.clicked.connect(self.load_list)
        self.ui.pushButton_4.clicked.connect(self.add_list)
        self.ui.pushButton_5.clicked.connect(self.del_list)


    def printf(self, messages:str):
        """
        输出到控制台（completed）
        :return:
        """
        self.ui.plainTextEdit.appendPlainText(messages)
        pass


    def load_base(self):
        """
        加载配置
        # TODO
        读取url, Cookie
        create session
        :return:
        """
        self.pid = self.ui.textEdit.toPlainText().strip()[-4::]
        try:
            int(self.pid)
        except ValueError:
            self.printf("错误(0X01): URL输入错误, 请检查URL是否有ID信息")
            return False
        else:
            self.printf("="*30)
            self.cookie = self.ui.textEdit_2.toPlainText().strip()
            self.printf(f"加载URL-ID&Cookies\nID:{self.pid}\nCookie:{self.cookie}")
            self.session = make_session(self.cookie, self.pid, self.printf)
            (self.id_list,
             self.name_list,
             self.teacher_list,
             self.n, pid,
             self.used_p) = course_info(self.session, self.pid, self.printf)
        return True

    def add_list(self):
        """
        添加到任务列表(Completed) 12/25-10:59
        :return:
        """
        # Read num
        if not self.n:
            self.printf("Error0X13: data无数据")
            return False
        try:
            want_index = int(self.ui.textEdit_5.toPlainText().strip())
        except ValueError:
            self.printf("Error0X09: 输入序列号有问题")
            return False
        else:
            # Add to list
            if want_index>=self.n:
                self.printf("Error0X10: 输入序列号超出范围")
                return False
            if self.id_list[want_index] in self.chose_list:
                self.printf("Error0X11: 已经添加过该课程")
                return False
            self.chose_list.append(self.id_list[want_index])
            self.printf(f"id:{self.id_list[want_index]}已成功添加到队列")
            return True


    def del_list(self):
        """
        删除列表 (Completed) 12/25-11:14
        :return:
        """
        # get and find num
        # Read num
        if not self.n:
            self.printf("Error0X14: 选择列表无数据")
            return False
        try:
            want_index = int(self.ui.textEdit_5.toPlainText().strip())
        except ValueError:
            self.printf("Error0X09: 输入序列号有问题")
            return False
        else:
            # Add to list
            if want_index >= self.n:
                self.printf("Error0X10: 输入序列号超出范围, 不在全部课程内")
                return False

            # search
            kill_id = self.id_list[want_index]
            try:
                kill_idx = self.chose_list.index(kill_id)
            except ValueError:
                self.printf("Error0X11: 在您的队列中未找到该序号")
                return False
            # del
            self.chose_list.pop(kill_idx)
            self.printf(f"队列中id:{self.id_list[want_index]}已成功删除")
            return True


    def go(self):
        """
        启动
        :return:
        """
        if self.whether_load or len(self.chose_list)==0 or not self.session:
            self.printf("="*30)
            self.printf("请检查是否正确配置或者任务队列是否有内容")
            return False
        self.load_list()
        grab_courses("1",
                     self.session,
                     self.chose_list,
                     self.pid,
                     self.used_p,
                     self.printf)
        return True


    def search(self):
        """
        搜寻
        # TODO
        :return:
        """
        pass


    def load_all(self):
        """
        读取全列表
        :return:
        """
        if self.n == 0 or self.id_list == [] or self.name_list==[] or self.teacher_list==[]:
            self.printf("Error0X06: 尚未加载网页数据")
            return False
        for i in range(self.n):
            self.printf("="*30)
            self.printf(f"序号: {i:<3}  "
                        f"课程ID: {self.id_list[i]:<10}  "
                        f"课程名称: {self.name_list[i]}  "
                        f"教师名称: {self.teacher_list[i] < 4}")
        return True

    def load_list(self):
        """
        读取任务列表
        :return:
        """
        if not self.chose_list:
            self.printf("="*30)
            self.printf("Error0X08: 队列中无内容")
            return False
        for i in self.chose_list:
            idx = self.id_list.index(i)
            self.printf(f"序号: {idx:<3}  "
                        f"课程ID: {self.id_list[idx]:<10}  "
                        f"课程名称: {self.name_list[idx]}  "
                        f"教师名称: {self.teacher_list[idx] < 4}")
        return True


if __name__ == '__main__':
    app = QApplication([])
    stats = Stats()
    stats.ui.show()
    app.exec()


